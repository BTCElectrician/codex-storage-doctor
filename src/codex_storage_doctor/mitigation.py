"""Backup-first application and rollback of doctor-owned triggers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from . import __version__
from .filesystem import nonlocal_filesystem_reason
from .planning import (
    LOG_DB_NAME,
    TRIGGER_NAMES,
    TRIGGER_SQL,
    PlanError,
    cross_boundary_reason,
    doctor_triggers_connection,
    log_triggers_connection,
    normalize_sql,
    observed_codex_version,
    read_only_connection,
    read_file_identity,
    schema_fingerprint_connection,
    sha256_text,
    validate_log_schema,
    validate_plan_document,
)
from .reports import write_private_json

MANIFEST_SCHEMA = "codex-storage-doctor.rollback.v1"
MIN_FREE_MARGIN = 10 * 1024 * 1024


class SafetyGateError(RuntimeError):
    """A requested mutation failed a preservation gate."""


ProcessScanner = Callable[..., Any]


def _utc_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _scan_dict(scan: Any) -> dict[str, Any]:
    if scan is None:
        return {}
    if isinstance(scan, dict):
        return scan
    to_dict = getattr(scan, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        return value if isinstance(value, dict) else {}
    result: dict[str, Any] = {}
    for name in (
        "complete",
        "status",
        "processes",
        "open_database_paths",
        "errors",
    ):
        if hasattr(scan, name):
            result[name] = getattr(scan, name)
    return result


def ensure_process_gate(
    database: Path,
    process_scanner: ProcessScanner | None = None,
) -> dict[str, Any]:
    if process_scanner is None:
        try:
            from .processes import scan_codex_processes
        except ImportError as error:
            raise SafetyGateError(
                "process detection unavailable; refusing mutation"
            ) from error
        process_scanner = scan_codex_processes
    try:
        scan = process_scanner(database_paths=(database,))
    except TypeError:
        scan = process_scanner((database,))
    except Exception as error:
        raise SafetyGateError(
            f"process detection failed; refusing mutation: {type(error).__name__}"
        ) from error
    data = _scan_dict(scan)
    complete = data.get("complete")
    if complete is None:
        status = str(data.get("status", "")).lower()
        complete = status in {"complete", "ok", "supported"}
    if not complete:
        raise SafetyGateError(
            "process/open-handle detection is partial; refusing mutation"
        )
    processes = data.get("processes") or []
    open_paths = data.get("open_database_paths") or []
    if processes or open_paths:
        raise SafetyGateError(
            "Codex appears to be running or holding the database; quit every "
            "Codex Desktop, CLI, IDE, WSL, and native session"
        )
    return data


def _connect_writable(path: Path) -> sqlite3.Connection:
    try:
        uri = f"{path.resolve(strict=True).as_uri()}?mode=rw"
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=1.0,
            isolation_level=None,
        )
    except (OSError, sqlite3.OperationalError) as error:
        raise SafetyGateError(
            "writable target is unavailable; refusing without creating a database"
        ) from error
    connection.execute("PRAGMA busy_timeout=1000")
    return connection


def _quick_check(connection: sqlite3.Connection, label: str) -> None:
    row = connection.execute("PRAGMA quick_check(1)").fetchone()
    if row is None or str(row[0]).lower() != "ok":
        raise SafetyGateError(f"{label} quick_check did not return ok")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _restrict(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
        actual = path.stat().st_mode & 0o777
    except OSError as error:
        if os.name != "nt":
            raise SafetyGateError(
                "restrictive artifact permissions could not be established"
            ) from error
        return
    if os.name != "nt" and actual != mode:
        raise SafetyGateError(
            "restrictive artifact permissions could not be established"
        )


def _ensure_backup_space(database: Path, artifact_root: Path) -> None:
    artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _restrict(artifact_root, 0o700)
    database_bytes = database.stat().st_size
    wal_path = Path(f"{database}-wal")
    try:
        wal_bytes = wal_path.stat().st_size
    except FileNotFoundError:
        wal_bytes = 0
    source_bytes = database_bytes + wal_bytes
    needed = max(source_bytes * 2, source_bytes + MIN_FREE_MARGIN)
    available = shutil.disk_usage(artifact_root).free
    if available < needed:
        raise SafetyGateError(
            f"insufficient free space for verified backup: need {needed} bytes"
        )


def _backup_database(
    database: Path,
    destination: Path,
) -> tuple[str, int]:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if destination.exists() or temporary.exists():
        raise SafetyGateError("refusing to overwrite an existing backup artifact")
    backup = sqlite3.connect(temporary)
    try:
        with read_only_connection(database) as source:
            source.backup(backup)
        _quick_check(backup, "backup")
    except BaseException:
        backup.close()
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    else:
        backup.close()
    _restrict(temporary, 0o600)
    temporary.replace(destination)
    _restrict(destination, 0o600)
    return _sha256_file(destination), destination.stat().st_size


def _storage_state(database: Path) -> tuple[tuple[int, int], tuple[int, int] | None]:
    database_stat = database.stat()
    wal_path = Path(f"{database}-wal")
    try:
        wal_stat = wal_path.stat()
    except FileNotFoundError:
        wal = None
    else:
        wal = (wal_stat.st_size, wal_stat.st_mtime_ns)
    return (database_stat.st_size, database_stat.st_mtime_ns), wal


def _same_file(left: Any, right: Any) -> bool:
    if not left.device or not left.inode:
        return True
    return bool(right.device == left.device and right.inode == left.inode)


def _manifest_digest_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {"manifest_digest", "rollback_token"}
    return {key: value for key, value in manifest.items() if key not in excluded}


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _manifest_digest_payload(manifest),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _seal_manifest(manifest: dict[str, Any]) -> None:
    digest = _manifest_digest(manifest)
    manifest["manifest_digest"] = digest
    manifest["rollback_token"] = f"ROLLBACK-{digest[:12].upper()}"


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise SafetyGateError("unsupported rollback manifest schema")
    expected = _manifest_digest(manifest)
    if manifest.get("manifest_digest") != expected:
        raise SafetyGateError("rollback manifest digest mismatch")
    token = f"ROLLBACK-{expected[:12].upper()}"
    if manifest.get("rollback_token") != token:
        raise SafetyGateError("rollback token mismatch")
    mode = str(manifest.get("mode", ""))
    if mode not in TRIGGER_SQL:
        raise SafetyGateError("unsupported rollback manifest mode")
    if manifest.get("trigger_name") != TRIGGER_NAMES[mode]:
        raise SafetyGateError("rollback manifest trigger name mismatch")
    expected_trigger_hash = sha256_text(normalize_sql(TRIGGER_SQL[mode]))
    if manifest.get("trigger_sql_sha256") != expected_trigger_hash:
        raise SafetyGateError("rollback manifest trigger SQL fingerprint mismatch")
    if manifest.get("status") not in {"prepared", "applied", "rolled_back"}:
        raise SafetyGateError("unsupported rollback manifest status")
    database = manifest.get("database")
    if not isinstance(database, str) or not database:
        raise SafetyGateError("rollback manifest lacks a database target")
    database_path = Path(database)
    if not database_path.is_absolute() or not LOG_DB_NAME.fullmatch(
        database_path.name
    ):
        raise SafetyGateError("rollback manifest database target is invalid")
    if manifest.get("database_name") != database_path.name:
        raise SafetyGateError("rollback manifest database name mismatch")
    identity = manifest.get("file_identity_at_apply")
    if not isinstance(identity, dict):
        raise SafetyGateError("rollback manifest lacks target file identity")
    for field in ("device", "inode"):
        if not isinstance(identity.get(field), int):
            raise SafetyGateError("rollback manifest file identity is invalid")


def apply_plan(
    plan: Mapping[str, Any],
    confirmation: str,
    *,
    process_scanner: ProcessScanner | None = None,
) -> dict[str, Any]:
    try:
        validate_plan_document(plan)
    except PlanError as error:
        raise SafetyGateError(str(error)) from error
    if confirmation != plan["confirmation_token"]:
        raise SafetyGateError("confirmation token does not match the plan")
    planned_version = plan.get("observed_codex_version")
    current_version = observed_codex_version()
    if (
        isinstance(planned_version, str)
        and current_version is None
    ):
        raise SafetyGateError(
            "current Codex version is unavailable; recreate the plan from the "
            "same external environment"
        )
    if (
        isinstance(planned_version, str)
        and planned_version != current_version
    ):
        raise SafetyGateError(
            "observed Codex version changed since planning; create a fresh plan"
        )

    database = Path(str(plan["database"])).expanduser().resolve(strict=True)
    boundary = cross_boundary_reason(database)
    if boundary:
        raise SafetyGateError(f"audit-only cross-boundary path: {boundary}")
    filesystem_reason = nonlocal_filesystem_reason(database)
    if filesystem_reason:
        raise SafetyGateError(filesystem_reason)
    identity = read_file_identity(database)
    planned_identity = plan.get("file_identity", {})
    if (
        identity.device
        and identity.inode
        and (
            identity.device != int(planned_identity.get("device", -1))
            or identity.inode != int(planned_identity.get("inode", -1))
        )
    ):
        raise SafetyGateError("database identity changed since planning")

    ensure_process_gate(database, process_scanner)
    mode = str(plan["mode"])
    trigger_name = str(plan["trigger_name"])
    trigger_sql = normalize_sql(TRIGGER_SQL[mode])
    with read_only_connection(database) as preflight:
        validate_log_schema(preflight, mode)
        _quick_check(preflight, "source")
        if schema_fingerprint_connection(preflight) != plan["base_schema_fingerprint"]:
            raise SafetyGateError("base schema changed since planning")
        preflight_triggers = doctor_triggers_connection(preflight)
        all_preflight_triggers = log_triggers_connection(preflight)
        conflicting_log_triggers = {
            name: sql
            for name, sql in all_preflight_triggers.items()
            if name != trigger_name or sql != trigger_sql
        }
        conflicting_doctor_triggers = {
            name: sql
            for name, sql in preflight_triggers.items()
            if name != trigger_name or sql != trigger_sql
        }
        if conflicting_log_triggers or conflicting_doctor_triggers:
            raise SafetyGateError(
                "a conflicting logs or doctor-prefixed trigger exists; rollback or "
                "remove that conflict first"
            )
        if preflight_triggers.get(trigger_name) == trigger_sql:
            return {
                "status": "already_applied",
                "database": str(database),
                "trigger_name": trigger_name,
                "changed": False,
            }

    artifact_root = Path(str(plan["artifact_root"])).expanduser().resolve()
    artifact_filesystem_reason = nonlocal_filesystem_reason(artifact_root)
    if artifact_filesystem_reason:
        raise SafetyGateError(
            f"rollback artifact root refused: {artifact_filesystem_reason}"
        )
    _ensure_backup_space(database, artifact_root)
    artifact_dir = artifact_root / f"{_utc_slug()}-{plan['plan_digest'][:8]}"
    artifact_dir.mkdir(mode=0o700)
    _restrict(artifact_dir, 0o700)
    backup_path = artifact_dir / "logs-before-apply.sqlite"
    manifest_path = artifact_dir / "rollback-manifest.json"

    storage_before_backup = _storage_state(database)
    backup_hash, backup_size = _backup_database(database, backup_path)
    if _storage_state(database) != storage_before_backup:
        raise SafetyGateError(
            "database or WAL changed during backup; refusing mutation"
        )
    ensure_process_gate(database, process_scanner)
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA,
        "tool_version": __version__,
        "status": "prepared",
        "prepared_at": _utc_slug(),
        "database": str(database),
        "database_name": database.name,
        "mode": mode,
        "trigger_name": trigger_name,
        "trigger_sql_sha256": sha256_text(trigger_sql),
        "base_schema_fingerprint_before": plan["base_schema_fingerprint"],
        "observed_codex_version": plan.get("observed_codex_version"),
        "backup_path": str(backup_path),
        "backup_sha256": backup_hash,
        "backup_size": backup_size,
        "backup_may_contain_private_diagnostics": True,
        "plan_digest": plan["plan_digest"],
        "file_identity_at_apply": identity.to_dict(),
    }
    _seal_manifest(manifest)
    write_private_json(manifest_path, manifest)

    connection = _connect_writable(database)
    transaction_open = False
    try:
        connection.execute("BEGIN EXCLUSIVE")
        transaction_open = True
        ensure_process_gate(database, process_scanner)
        if _storage_state(database) != storage_before_backup:
            raise SafetyGateError(
                "database or WAL changed after backup; refusing mutation"
            )
        final_identity = read_file_identity(database)
        if (
            identity.device
            and identity.inode
            and (
                final_identity.device != identity.device
                or final_identity.inode != identity.inode
            )
        ):
            raise SafetyGateError("database identity changed during backup")
        validate_log_schema(connection, mode)
        current_fingerprint = schema_fingerprint_connection(connection)
        if current_fingerprint != plan["base_schema_fingerprint"]:
            raise SafetyGateError("base schema changed since planning")
        triggers = doctor_triggers_connection(connection)
        all_triggers = log_triggers_connection(connection)
        conflicting_log_triggers = {
            name: sql
            for name, sql in all_triggers.items()
            if name != trigger_name or sql != trigger_sql
        }
        conflicting_doctor_triggers = {
            name: sql
            for name, sql in triggers.items()
            if name != trigger_name or sql != trigger_sql
        }
        if conflicting_log_triggers or conflicting_doctor_triggers:
            raise SafetyGateError(
                "a conflicting logs or doctor-prefixed trigger exists; rollback or "
                "remove that conflict first"
            )
        if triggers.get(trigger_name) == trigger_sql:
            connection.execute("ROLLBACK")
            transaction_open = False
            return {
                "status": "already_applied",
                "database": str(database),
                "trigger_name": trigger_name,
                "changed": False,
            }
        _quick_check(connection, "source")
        connection.execute(TRIGGER_SQL[mode])
        connection.execute("COMMIT")
        transaction_open = False
        with read_only_connection(database) as verify:
            installed = doctor_triggers_connection(verify)
            if installed.get(trigger_name) != trigger_sql:
                raise SafetyGateError("trigger verification failed after commit")
            after = schema_fingerprint_connection(verify)
        manifest["status"] = "applied"
        manifest["applied_at"] = _utc_slug()
        manifest["base_schema_fingerprint_after"] = after
        _seal_manifest(manifest)
        write_private_json(manifest_path, manifest, overwrite=True)
        return {
            "status": "applied",
            "changed": True,
            "database": str(database),
            "trigger_name": trigger_name,
            "manifest": str(manifest_path),
            "backup": str(backup_path),
            "backup_sha256": backup_hash,
            "rollback_token": manifest["rollback_token"],
        }
    except sqlite3.OperationalError as error:
        if transaction_open:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise SafetyGateError(
            f"SQLite refused the exclusive mutation: {error}"
        ) from error
    except BaseException:
        if transaction_open:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise
    finally:
        connection.close()


def rollback(
    manifest: Mapping[str, Any],
    confirmation: str,
    *,
    process_scanner: ProcessScanner | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    validate_manifest(manifest)
    if confirmation != manifest["rollback_token"]:
        raise SafetyGateError("confirmation token does not match the manifest")
    database = Path(str(manifest["database"])).expanduser().resolve(strict=True)
    boundary = cross_boundary_reason(database)
    if boundary:
        raise SafetyGateError(f"audit-only cross-boundary path: {boundary}")
    filesystem_reason = nonlocal_filesystem_reason(database)
    if filesystem_reason:
        raise SafetyGateError(filesystem_reason)
    ensure_process_gate(database, process_scanner)
    planned_identity = manifest.get("file_identity_at_apply")
    if not isinstance(planned_identity, dict):
        raise SafetyGateError("rollback manifest lacks target file identity")
    initial_identity = read_file_identity(database)
    if (
        initial_identity.device
        and initial_identity.inode
        and (
            initial_identity.device != int(planned_identity.get("device", -1))
            or initial_identity.inode != int(planned_identity.get("inode", -1))
        )
    ):
        raise SafetyGateError("rollback target identity changed")

    artifact_dir = Path(str(manifest["backup_path"])).resolve().parent
    artifact_filesystem_reason = nonlocal_filesystem_reason(artifact_dir)
    if artifact_filesystem_reason:
        raise SafetyGateError(
            f"rollback artifact root refused: {artifact_filesystem_reason}"
        )
    _ensure_backup_space(database, artifact_dir)
    backup_path = artifact_dir / f"logs-before-rollback-{_utc_slug()}.sqlite"
    trigger_name = str(manifest["trigger_name"])
    expected_trigger_hash = str(manifest["trigger_sql_sha256"])

    with read_only_connection(database) as preflight:
        validate_log_schema(preflight, str(manifest["mode"]))
        if (
            schema_fingerprint_connection(preflight)
            != manifest["base_schema_fingerprint_before"]
        ):
            raise SafetyGateError("base schema changed since mitigation")
        doctor_triggers = doctor_triggers_connection(preflight)
        unexpected_doctor_triggers = set(doctor_triggers).difference(
            {trigger_name}
        )
        if unexpected_doctor_triggers:
            raise SafetyGateError(
                "an unexpected doctor-prefixed trigger exists; refusing rollback"
            )
        installed_sql = doctor_triggers.get(trigger_name)
        if installed_sql is None:
            updated = dict(manifest)
            updated["status"] = "rolled_back"
            updated["rolled_back_at"] = _utc_slug()
            _seal_manifest(updated)
            if manifest_path is not None:
                write_private_json(manifest_path, updated, overwrite=True)
            return {
                "status": "already_rolled_back",
                "changed": False,
                "database": str(database),
                "trigger_name": trigger_name,
                "manifest_reconciled": manifest_path is not None,
            }
        if sha256_text(installed_sql) != expected_trigger_hash:
            raise SafetyGateError(
                "installed trigger differs from the rollback manifest"
            )

    storage_before_backup = _storage_state(database)
    backup_hash, _ = _backup_database(database, backup_path)
    if _storage_state(database) != storage_before_backup:
        raise SafetyGateError(
            "database or WAL changed during rollback backup; refusing mutation"
        )
    ensure_process_gate(database, process_scanner)
    connection = _connect_writable(database)
    transaction_open = False
    try:
        connection.execute("BEGIN EXCLUSIVE")
        transaction_open = True
        ensure_process_gate(database, process_scanner)
        if _storage_state(database) != storage_before_backup:
            raise SafetyGateError(
                "database or WAL changed after rollback backup; refusing mutation"
            )
        final_identity = read_file_identity(database)
        if not _same_file(initial_identity, final_identity):
            raise SafetyGateError("rollback target identity changed during backup")
        validate_log_schema(connection, str(manifest["mode"]))
        if (
            schema_fingerprint_connection(connection)
            != manifest["base_schema_fingerprint_before"]
        ):
            raise SafetyGateError("base schema changed since mitigation")
        triggers = doctor_triggers_connection(connection)
        unexpected_doctor_triggers = set(triggers).difference({trigger_name})
        if unexpected_doctor_triggers:
            raise SafetyGateError(
                "an unexpected doctor-prefixed trigger exists; refusing rollback"
            )
        installed_sql = triggers.get(trigger_name)
        if installed_sql is None:
            connection.execute("ROLLBACK")
            transaction_open = False
            updated = dict(manifest)
            updated["status"] = "rolled_back"
            updated["rolled_back_at"] = _utc_slug()
            _seal_manifest(updated)
            if manifest_path is not None:
                write_private_json(manifest_path, updated, overwrite=True)
            return {
                "status": "already_rolled_back",
                "changed": False,
                "database": str(database),
                "trigger_name": trigger_name,
                "manifest_reconciled": manifest_path is not None,
            }
        if sha256_text(installed_sql) != expected_trigger_hash:
            raise SafetyGateError(
                "installed trigger differs from the rollback manifest"
            )
        _quick_check(connection, "source")
        quoted_name = '"' + trigger_name.replace('"', '""') + '"'
        connection.execute(f"DROP TRIGGER {quoted_name}")
        connection.execute("COMMIT")
        transaction_open = False
    except sqlite3.OperationalError as error:
        if transaction_open:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise SafetyGateError(
            f"SQLite refused the exclusive rollback: {error}"
        ) from error
    except BaseException:
        if transaction_open:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise
    finally:
        connection.close()

    with read_only_connection(database) as verify:
        remaining_doctor_triggers = doctor_triggers_connection(verify)
        if remaining_doctor_triggers:
            raise SafetyGateError("trigger verification failed after rollback")
        if (
            schema_fingerprint_connection(verify)
            != manifest["base_schema_fingerprint_before"]
        ):
            raise SafetyGateError("base schema changed during rollback")

    updated = dict(manifest)
    updated["status"] = "rolled_back"
    updated["rolled_back_at"] = _utc_slug()
    _seal_manifest(updated)
    if manifest_path is not None:
        write_private_json(manifest_path, updated, overwrite=True)
    rollback_record = {
        "schema_version": "codex-storage-doctor.rollback-result.v1",
        "status": "rolled_back",
        "database": str(database),
        "trigger_name": trigger_name,
        "backup_path": str(backup_path),
        "backup_sha256": backup_hash,
        "rolled_back_at": _utc_slug(),
    }
    rollback_record_path = artifact_dir / "rollback-result.json"
    write_private_json(rollback_record_path, rollback_record)
    return {
        **rollback_record,
        "changed": True,
        "record": str(rollback_record_path),
    }
