"""Immutable mitigation plans and schema identity."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sqlite3
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import __version__
from .filesystem import nonlocal_filesystem_reason
from .schema import BODY_COLUMNS, REQUIRED_LOG_COLUMNS

PLAN_SCHEMA = "codex-storage-doctor.plan.v1"
DOCTOR_TRIGGER_PREFIX = "codex_storage_doctor_v1_"
TRIGGER_NAMES = {
    "balanced": f"{DOCTOR_TRIGGER_PREFIX}balanced",
    "maximum": f"{DOCTOR_TRIGGER_PREFIX}maximum",
}
TRIGGER_SQL = {
    "balanced": """
CREATE TRIGGER codex_storage_doctor_v1_balanced
BEFORE INSERT ON logs
WHEN UPPER(COALESCE(NEW.level, '')) IN ('TRACE', 'DEBUG', 'INFO')
BEGIN
  SELECT RAISE(IGNORE);
END
""".strip(),
    "maximum": """
CREATE TRIGGER codex_storage_doctor_v1_maximum
BEFORE INSERT ON logs
BEGIN
  SELECT RAISE(IGNORE);
END
""".strip(),
}
LOG_DB_NAME = re.compile(r"^logs_[0-9]+\.sqlite$", re.IGNORECASE)


class PlanError(RuntimeError):
    """A plan cannot be created or validated safely."""


class CrossBoundaryError(PlanError):
    """A Windows/WSL cross-boundary target is audit-only."""


class SafetyBoundaryError(PlanError):
    """A mutation target fails a native/local boundary."""


@dataclass(frozen=True)
class FileIdentity:
    size: int
    mtime_ns: int
    device: int
    inode: int

    def to_dict(self) -> dict[str, int]:
        return {
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "device": self.device,
            "inode": self.inode,
        }


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_sql(sql: str) -> str:
    return " ".join(sql.strip().rstrip(";").split())


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value)
    )


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def read_file_identity(path: Path) -> FileIdentity:
    stat = path.stat()
    return FileIdentity(
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        device=getattr(stat, "st_dev", 0),
        inode=getattr(stat, "st_ino", 0),
    )


@contextmanager
def read_only_connection(path: Path) -> Iterator[sqlite3.Connection]:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2.0)
    try:
        connection.execute("PRAGMA query_only=ON")
        yield connection
    finally:
        connection.close()


def schema_fingerprint_connection(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, COALESCE(sql, '')
        FROM sqlite_master
        WHERE type IN ('table', 'index', 'trigger')
          AND name NOT GLOB ?
        ORDER BY type, name
        """,
        (f"{DOCTOR_TRIGGER_PREFIX}*",),
    ).fetchall()
    normalized = [
        [str(kind), str(name), str(table), normalize_sql(str(sql))]
        for kind, name, table, sql in rows
    ]
    return hashlib.sha256(canonical_json({"schema": normalized})).hexdigest()


def schema_fingerprint(path: Path) -> str:
    with read_only_connection(path) as connection:
        return schema_fingerprint_connection(connection)


def doctor_triggers_connection(
    connection: sqlite3.Connection,
) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT name, COALESCE(sql, '')
        FROM sqlite_master
        WHERE type = 'trigger' AND name GLOB ?
        ORDER BY name
        """,
        (f"{DOCTOR_TRIGGER_PREFIX}*",),
    ).fetchall()
    return {str(name): normalize_sql(str(sql)) for name, sql in rows}


def log_triggers_connection(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT name, COALESCE(sql, '')
        FROM sqlite_master
        WHERE type = 'trigger' AND tbl_name = 'logs'
        ORDER BY name
        """
    ).fetchall()
    return {str(name): normalize_sql(str(sql)) for name, sql in rows}


def validate_log_schema(connection: sqlite3.Connection, mode: str) -> list[str]:
    if mode not in TRIGGER_SQL:
        raise PlanError(f"unsupported mitigation mode: {mode}")
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='logs'"
    ).fetchone()
    if table is None:
        raise PlanError("unsupported database: required logs table is absent")
    columns = [
        str(row[1])
        for row in connection.execute("PRAGMA table_info(logs)").fetchall()
    ]
    names = frozenset(columns)
    missing = sorted(REQUIRED_LOG_COLUMNS.difference(names))
    if missing:
        raise PlanError(
            "unsupported logs schema; missing columns: " + ", ".join(missing)
        )
    if not BODY_COLUMNS.intersection(names):
        raise PlanError(
            "unsupported logs schema; no recognized diagnostic body column"
        )
    return columns


def observed_codex_version() -> str | None:
    try:
        result = subprocess.run(
            ["codex", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip().splitlines()
    return value[0][:128] if value else None


def is_wsl(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return True
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(
            encoding="utf-8", errors="ignore"
        )
    except OSError:
        return False
    return "microsoft" in release.lower() or "wsl" in release.lower()


def cross_boundary_reason(
    path: Path,
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    system = (platform_name or platform.system()).lower()
    raw = str(path)
    normalized = raw.replace("\\", "/").lower()
    if system == "windows" and (
        normalized.startswith("//wsl$/")
        or normalized.startswith("//wsl.localhost/")
    ):
        return "Windows cannot mutate a WSL database; run the doctor inside WSL"
    if (system == "linux" and is_wsl(environ)) and re.match(
        r"^/mnt/[a-z](?:/|$)", normalized
    ):
        return (
            "WSL cannot mutate a Windows-hosted database; run the doctor in "
            "native Windows"
        )
    return None


def _plan_digest_payload(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in plan.items()
        if key not in {"plan_digest", "confirmation_token"}
    }


def calculate_plan_digest(plan: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(_plan_digest_payload(plan))).hexdigest()


def expected_artifact_root(database: Path) -> Path:
    return database.parent / ".codex-storage-doctor" / "rollback"


def create_plan(
    database: Path,
    mode: str,
    *,
    process_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    path = database.expanduser().resolve(strict=True)
    if not path.is_file():
        raise PlanError(f"database is not a regular file: {path}")
    if not LOG_DB_NAME.fullmatch(path.name):
        raise PlanError(
            "refusing non-log database; expected an explicit logs_<n>.sqlite path"
        )
    boundary = cross_boundary_reason(path)
    if boundary:
        raise CrossBoundaryError(f"audit-only cross-boundary path: {boundary}")
    filesystem_reason = nonlocal_filesystem_reason(path)
    if filesystem_reason:
        raise SafetyBoundaryError(filesystem_reason)
    with read_only_connection(path) as connection:
        validate_log_schema(connection, mode)
        quick_check = connection.execute("PRAGMA quick_check(1)").fetchone()
        if quick_check is None or str(quick_check[0]).lower() != "ok":
            raise PlanError("source database quick_check did not return ok")
        triggers = doctor_triggers_connection(connection)
        all_log_triggers = log_triggers_connection(connection)
        base_fingerprint = schema_fingerprint_connection(connection)

    requested_name = TRIGGER_NAMES[mode]
    requested_sql = normalize_sql(TRIGGER_SQL[mode])
    requested_digest = sha256_text(requested_sql)
    conflicting_log_triggers = {
        name: sha256_text(sql)
        for name, sql in all_log_triggers.items()
        if name != requested_name or sql != requested_sql
    }
    conflicting_doctor_triggers = {
        name: sha256_text(sql)
        for name, sql in triggers.items()
        if name != requested_name or sql != requested_sql
    }
    if conflicting_log_triggers or conflicting_doctor_triggers:
        raise PlanError(
            "a conflicting logs or Codex Storage Doctor trigger exists; "
            "rollback first"
        )

    identity = read_file_identity(path)
    artifact_root = expected_artifact_root(path)
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA,
        "tool_version": __version__,
        "created_at": utc_now(),
        "database": str(path),
        "database_name": path.name,
        "mode": mode,
        "suppresses": (
            ["TRACE", "DEBUG", "INFO"]
            if mode == "balanced"
            else ["ALL"]
        ),
        "preserves": (
            ["WARN", "ERROR", "UNKNOWN"] if mode == "balanced" else []
        ),
        "file_identity": {
            "device": identity.device,
            "inode": identity.inode,
        },
        "observed_file_stat": {
            "size": identity.size,
            "mtime_ns": identity.mtime_ns,
            "informational_only": True,
        },
        "base_schema_fingerprint": base_fingerprint,
        "trigger_name": requested_name,
        "trigger_sql_sha256": requested_digest,
        "already_installed": triggers.get(requested_name) == requested_sql,
        "observed_codex_version": observed_codex_version(),
        "process_gate_at_plan": {
            "status": str((process_observation or {}).get("status", "not_sampled")),
            "complete": bool((process_observation or {}).get("complete", False)),
            "codex_running": bool(
                (process_observation or {}).get("codex_running", False)
            ),
            "handle_evidence_supported": bool(
                (process_observation or {}).get(
                    "handle_evidence_supported", False
                )
            ),
            "apply_will_rescan": True,
        },
        "artifact_root": str(artifact_root),
        "safety": {
            "requires_codex_closed": True,
            "verified_backup_first": True,
            "deletes_rows": False,
            "runs_vacuum": False,
            "changes_journal_mode": False,
            "installs_background_job": False,
            "backup_may_contain_private_diagnostics": True,
        },
    }
    digest = calculate_plan_digest(plan)
    plan["plan_digest"] = digest
    plan["confirmation_token"] = f"APPLY-{digest[:12].upper()}"
    return plan


def validate_plan_document(plan: Mapping[str, Any]) -> None:
    if plan.get("schema_version") != PLAN_SCHEMA:
        raise PlanError("unsupported plan schema")
    if plan.get("tool_version") != __version__:
        raise PlanError("plan tool version mismatch; create a fresh plan")
    mode = str(plan.get("mode", ""))
    if mode not in TRIGGER_SQL:
        raise PlanError("unsupported plan mode")
    database_value = plan.get("database")
    if not isinstance(database_value, str) or not database_value:
        raise PlanError("plan database target is invalid")
    database = Path(database_value)
    if not database.is_absolute() or not LOG_DB_NAME.fullmatch(database.name):
        raise PlanError("plan database target is invalid")
    if plan.get("database_name") != database.name:
        raise PlanError("plan database target name mismatch")
    artifact_root_value = plan.get("artifact_root")
    if not isinstance(artifact_root_value, str) or not artifact_root_value:
        raise PlanError("plan artifact root is invalid")
    artifact_root = Path(artifact_root_value)
    if not artifact_root.is_absolute():
        raise PlanError("plan artifact root is invalid")
    expected_root = expected_artifact_root(database)
    if os.path.normcase(os.path.normpath(str(artifact_root))) != os.path.normcase(
        os.path.normpath(str(expected_root))
    ):
        raise PlanError("plan artifact root does not match the database target")
    identity = plan.get("file_identity")
    if not isinstance(identity, Mapping):
        raise PlanError("plan file identity is invalid")
    for field in ("device", "inode"):
        value = identity.get(field)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise PlanError("plan file identity is invalid")
    if not _is_sha256(plan.get("base_schema_fingerprint")):
        raise PlanError("plan base schema fingerprint is invalid")
    expected_digest = calculate_plan_digest(plan)
    if plan.get("plan_digest") != expected_digest:
        raise PlanError("plan digest mismatch; artifact was changed")
    expected_token = f"APPLY-{expected_digest[:12].upper()}"
    if plan.get("confirmation_token") != expected_token:
        raise PlanError("plan confirmation token mismatch")
    if plan.get("trigger_name") != TRIGGER_NAMES[mode]:
        raise PlanError("plan trigger name mismatch")
    if plan.get("trigger_sql_sha256") != sha256_text(
        normalize_sql(TRIGGER_SQL[mode])
    ):
        raise PlanError("plan trigger SQL fingerprint mismatch")
