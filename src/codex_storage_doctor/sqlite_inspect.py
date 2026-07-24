"""Allowlisted, read-only inspection of a Codex diagnostic SQLite database."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from typing import Any

from .models import (
    DatabaseInspection,
    Finding,
    FindingSeverity,
    KNOWN_LEVELS,
    LevelAggregate,
    SchemaColumn,
)
from .planning import TRIGGER_NAMES, TRIGGER_SQL, normalize_sql
from .schema import BODY_COLUMNS, REQUIRED_LOG_COLUMNS


FULL_SCAN_THRESHOLD_BYTES = 256 * 1024 * 1024
DOCTOR_TRIGGER_NAMES: tuple[str, ...] = tuple(sorted(TRIGGER_NAMES.values()))


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _sizes(path: Path) -> tuple[int, int, int]:
    return (
        _size(path),
        _size(Path(f"{path}-wal")),
        _size(Path(f"{path}-shm")),
    )


def _readonly_uri(path: Path) -> str:
    # ``as_uri`` percent-encodes spaces and prevents query-string injection.
    return f"{path.absolute().as_uri()}?mode=ro"


def _is_readonly_cantinit(error: sqlite3.OperationalError) -> bool:
    error_name = getattr(error, "sqlite_errorname", "")
    if error_name == "SQLITE_READONLY_CANTINIT":
        return True
    extended = getattr(sqlite3, "SQLITE_READONLY_CANTINIT", None)
    return extended is not None and getattr(error, "sqlite_errorcode", None) == extended


def _columns(connection: sqlite3.Connection) -> tuple[SchemaColumn, ...]:
    rows = connection.execute("PRAGMA table_info('logs')").fetchall()
    return tuple(
        SchemaColumn(
            name=str(row[1]),
            declared_type=str(row[2] or ""),
            not_null=bool(row[3]),
            primary_key_position=int(row[5]),
        )
        for row in rows
    )


def _quick_check(connection: sqlite3.Connection) -> bool:
    # Do not return arbitrary corruption details. Only the allowlisted boolean
    # crosses the inspection boundary.
    row = connection.execute("PRAGMA quick_check(1)").fetchone()
    return bool(row and row[0] == "ok")


def _doctor_triggers(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    placeholders = ", ".join("?" for _ in DOCTOR_TRIGGER_NAMES)
    rows = connection.execute(
        (
            "SELECT name, COALESCE(sql, '') FROM sqlite_master "
            f"WHERE type = 'trigger' AND name IN ({placeholders}) ORDER BY name"
        ),
        DOCTOR_TRIGGER_NAMES,
    ).fetchall()
    expected_by_name = {
        TRIGGER_NAMES[mode]: normalize_sql(sql) for mode, sql in TRIGGER_SQL.items()
    }
    exact: list[str] = []
    altered: list[str] = []
    for raw_name, raw_sql in rows:
        name = str(raw_name)
        if normalize_sql(str(raw_sql)) == expected_by_name[name]:
            exact.append(name)
        else:
            altered.append(name)
    return tuple(exact), tuple(altered)


def _sequence(connection: sqlite3.Connection) -> int | None:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
    ).fetchone()
    if not exists:
        return None
    row = connection.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = ?", ("logs",)
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _full_aggregates(
    connection: sqlite3.Connection,
    column_names: frozenset[str],
) -> tuple[
    int,
    int | None,
    int | float | None,
    tuple[LevelAggregate, ...],
]:
    row = connection.execute("SELECT COUNT(*), MAX(id) FROM logs").fetchone()
    row_count = int(row[0])
    max_id = int(row[1]) if row[1] is not None else None
    has_estimated_bytes = "estimated_bytes" in column_names
    if has_estimated_bytes:
        sum_row = connection.execute(
            """
            SELECT COALESCE(
                SUM(
                    CASE
                        WHEN typeof(estimated_bytes) IN ('integer', 'real')
                        THEN estimated_bytes
                        ELSE 0
                    END
                ),
                0
            )
            FROM logs
            """
        ).fetchone()
        estimated_bytes: int | float = sum_row[0]
        aggregate_sql = """
            SELECT
                CASE
                    WHEN UPPER(COALESCE(level, '')) IN
                        ('TRACE', 'DEBUG', 'INFO', 'WARN', 'ERROR')
                    THEN UPPER(COALESCE(level, ''))
                    ELSE 'OTHER'
                END AS safe_level,
                COUNT(*),
                COALESCE(
                    SUM(
                        CASE
                            WHEN typeof(estimated_bytes) IN ('integer', 'real')
                            THEN estimated_bytes
                            ELSE 0
                        END
                    ),
                    0
                )
            FROM logs
            GROUP BY safe_level
        """
    else:
        estimated_bytes = None
        aggregate_sql = """
            SELECT
                CASE
                    WHEN UPPER(COALESCE(level, '')) IN
                        ('TRACE', 'DEBUG', 'INFO', 'WARN', 'ERROR')
                    THEN UPPER(COALESCE(level, ''))
                    ELSE 'OTHER'
                END AS safe_level,
                COUNT(*),
                0
            FROM logs
            GROUP BY safe_level
        """
    by_level = {
        str(level): (int(rows), byte_count)
        for level, rows, byte_count in connection.execute(aggregate_sql).fetchall()
    }
    aggregates = tuple(
        LevelAggregate(
            level=level,
            rows=by_level.get(level, (0, 0))[0],
            estimated_bytes=by_level.get(level, (0, 0))[1],
        )
        for level in KNOWN_LEVELS
    )
    return row_count, max_id, estimated_bytes, aggregates


def _failed_inspection(
    path: Path,
    *,
    status: str,
    exists: bool,
    code: str,
    message: str,
    partial: bool,
) -> DatabaseInspection:
    database_size, wal_size, shm_size = _sizes(path)
    return DatabaseInspection(
        path=path,
        status=status,
        exists=exists,
        database_size_bytes=database_size,
        wal_size_bytes=wal_size,
        shm_size_bytes=shm_size,
        findings=(
            Finding(
                code=code,
                message=message,
                severity=FindingSeverity.WARNING if partial else FindingSeverity.ERROR,
                partial=partial,
            ),
        ),
    )


def inspect_database(
    path: str | os.PathLike[str],
    full_scan: bool = False,
) -> DatabaseInspection:
    """Inspect only metadata and allowlisted aggregates through ``mode=ro``."""

    database_path = Path(path).expanduser().absolute()
    if not database_path.is_file():
        return _failed_inspection(
            database_path,
            status="error",
            exists=False,
            code="database_not_found",
            message="The selected diagnostic database does not exist.",
            partial=False,
        )

    database_size, wal_size, shm_size = _sizes(database_path)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            _readonly_uri(database_path),
            uri=True,
            timeout=1.0,
        )
        connection.execute("PRAGMA query_only = ON")
        quick_check_ok = _quick_check(connection)
        columns = _columns(connection)
        column_names = frozenset(column.name for column in columns)
        schema_supported = (
            REQUIRED_LOG_COLUMNS.issubset(column_names)
            and bool(BODY_COLUMNS.intersection(column_names))
        )
        triggers, altered_triggers = _doctor_triggers(connection)
        sequence = _sequence(connection) if "id" in column_names else None
        findings: list[Finding] = []

        if not quick_check_ok:
            findings.append(
                Finding(
                    code="quick_check_failed",
                    message="SQLite quick_check did not report a healthy database.",
                    severity=FindingSeverity.ERROR,
                )
            )
        if not schema_supported:
            findings.append(
                Finding(
                    code="unsupported_logs_schema",
                    message="The logs table is absent or lacks required metadata columns.",
                    severity=FindingSeverity.ERROR,
                )
            )
        if altered_triggers:
            findings.append(
                Finding(
                    code="doctor_trigger_sql_mismatch",
                    message=(
                        "A doctor-named trigger exists but its SQL does not match "
                        "the built-in mitigation definition."
                    ),
                    severity=FindingSeverity.ERROR,
                )
            )

        run_full_scan = schema_supported and (
            full_scan or database_size <= FULL_SCAN_THRESHOLD_BYTES
        )
        row_count: int | None = None
        max_id: int | None = None
        estimated_bytes: int | float | None = None
        aggregates: tuple[LevelAggregate, ...] = ()
        if run_full_scan:
            row_count, max_id, estimated_bytes, aggregates = _full_aggregates(
                connection, column_names
            )
        elif schema_supported:
            findings.append(
                Finding(
                    code="full_scan_skipped",
                    message=(
                        "Row and level aggregates were skipped because the database "
                        "exceeds the 256 MiB default threshold."
                    ),
                    severity=FindingSeverity.INFO,
                )
            )

        status = "ok"
        if not quick_check_ok or not schema_supported or altered_triggers:
            status = "error"
        return DatabaseInspection(
            path=database_path,
            status=status,
            exists=True,
            database_size_bytes=database_size,
            wal_size_bytes=wal_size,
            shm_size_bytes=shm_size,
            quick_check_ok=quick_check_ok,
            schema_supported=schema_supported,
            schema_columns=columns,
            doctor_triggers=triggers,
            altered_doctor_triggers=altered_triggers,
            full_scan_performed=run_full_scan,
            row_count=row_count,
            max_id=max_id,
            sqlite_sequence=sequence,
            estimated_bytes=estimated_bytes,
            level_aggregates=aggregates,
            findings=tuple(findings),
        )
    except sqlite3.OperationalError as error:
        if _is_readonly_cantinit(error):
            return _failed_inspection(
                database_path,
                status="partial",
                exists=True,
                code="wal_readonly_cantinit",
                message=(
                    "SQLite could not initialize read state for the WAL database; "
                    "inspection is partial."
                ),
                partial=True,
            )
        return _failed_inspection(
            database_path,
            status="error",
            exists=True,
            code="sqlite_read_failed",
            message="The diagnostic database could not be inspected read-only.",
            partial=False,
        )
    except sqlite3.DatabaseError:
        return _failed_inspection(
            database_path,
            status="error",
            exists=True,
            code="sqlite_read_failed",
            message="The diagnostic database could not be inspected read-only.",
            partial=False,
        )
    finally:
        if connection is not None:
            connection.close()
