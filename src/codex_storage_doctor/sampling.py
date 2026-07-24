"""Deterministic before/after observations of logical database activity."""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Callable

from .models import (
    DatabaseInspection,
    Finding,
    FindingSeverity,
    KNOWN_LEVELS,
    LevelAggregate,
    LogicalSnapshot,
    ProcessScan,
    SampleDelta,
    SampleResult,
)
from .processes import scan_codex_processes
from .sqlite_inspect import inspect_database


InspectionFunction = Callable[[str | os.PathLike[str], bool], DatabaseInspection]
ProcessScanFunction = Callable[[tuple[Path, ...]], ProcessScan]


def _snapshot(
    inspection: DatabaseInspection,
    scan: ProcessScan,
) -> LogicalSnapshot:
    return LogicalSnapshot(
        database_size_bytes=inspection.database_size_bytes,
        wal_size_bytes=inspection.wal_size_bytes,
        shm_size_bytes=inspection.shm_size_bytes,
        row_count=inspection.row_count,
        max_id=inspection.max_id,
        sqlite_sequence=inspection.sqlite_sequence,
        estimated_bytes=inspection.estimated_bytes,
        levels=inspection.level_aggregates,
        process_write_bytes=scan.total_write_bytes,
    )


def _optional_delta(
    before: int | float | None,
    after: int | float | None,
) -> int | float | None:
    if before is None or after is None:
        return None
    return after - before


def _level_delta(
    before: tuple[LevelAggregate, ...],
    after: tuple[LevelAggregate, ...],
) -> tuple[LevelAggregate, ...]:
    if not before or not after:
        return ()
    before_by_level = {aggregate.level: aggregate for aggregate in before}
    after_by_level = {aggregate.level: aggregate for aggregate in after}
    return tuple(
        LevelAggregate(
            level=level,
            rows=after_by_level.get(level, LevelAggregate(level, 0, 0)).rows
            - before_by_level.get(level, LevelAggregate(level, 0, 0)).rows,
            estimated_bytes=(
                after_by_level.get(level, LevelAggregate(level, 0, 0)).estimated_bytes
                - before_by_level.get(level, LevelAggregate(level, 0, 0)).estimated_bytes
            ),
        )
        for level in KNOWN_LEVELS
    )


def _delta(before: LogicalSnapshot, after: LogicalSnapshot) -> SampleDelta:
    return SampleDelta(
        database_size_bytes=after.database_size_bytes - before.database_size_bytes,
        wal_size_bytes=after.wal_size_bytes - before.wal_size_bytes,
        shm_size_bytes=after.shm_size_bytes - before.shm_size_bytes,
        row_count=_optional_delta(before.row_count, after.row_count),  # type: ignore[arg-type]
        max_id=_optional_delta(before.max_id, after.max_id),  # type: ignore[arg-type]
        sqlite_sequence=_optional_delta(  # type: ignore[arg-type]
            before.sqlite_sequence, after.sqlite_sequence
        ),
        estimated_bytes=_optional_delta(
            before.estimated_bytes, after.estimated_bytes
        ),
        levels=_level_delta(before.levels, after.levels),
        process_write_bytes=_optional_delta(  # type: ignore[arg-type]
            before.process_write_bytes, after.process_write_bytes
        ),
    )


def _get_scan(
    source: ProcessScan | ProcessScanFunction | None,
    path: Path,
) -> ProcessScan:
    if source is None:
        return scan_codex_processes((path,))
    if isinstance(source, ProcessScan):
        return source
    return source((path,))


def sample_database(
    path: str | os.PathLike[str],
    seconds: float,
    process_scan: ProcessScan | ProcessScanFunction | None = None,
    *,
    full_scan: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
    inspect_fn: InspectionFunction = inspect_database,
) -> SampleResult:
    """Take two bounded snapshots without translating them into drive wear."""

    if seconds < 0:
        raise ValueError("sample seconds must be non-negative")
    if seconds > 86_400:
        raise ValueError("sample seconds exceed the one-day safety bound")
    database_path = Path(path).expanduser().absolute()

    before_inspection = inspect_fn(database_path, full_scan)
    before_scan = _get_scan(process_scan, database_path)
    sleep_fn(seconds)
    after_inspection = inspect_fn(database_path, full_scan)
    after_scan = _get_scan(process_scan, database_path)

    before = _snapshot(before_inspection, before_scan)
    after = _snapshot(after_inspection, after_scan)
    findings: list[Finding] = []
    findings.extend(before_inspection.findings)
    findings.extend(after_inspection.findings)
    findings.extend(before_scan.findings)
    findings.extend(after_scan.findings)

    status = "ok"
    if before_inspection.status == "error" or after_inspection.status == "error":
        status = "error"
    elif any(
        value in {"partial", "unsupported"}
        for value in (
            before_inspection.status,
            after_inspection.status,
            before_scan.status,
            after_scan.status,
        )
    ):
        status = "partial"

    if not before_inspection.full_scan_performed or not after_inspection.full_scan_performed:
        findings.append(
            Finding(
                code="sample_logical_aggregates_unavailable",
                message=(
                    "One or more logical aggregate snapshots were unavailable; "
                    "the bounded sample is incomplete."
                ),
                severity=FindingSeverity.WARNING,
                partial=True,
            )
        )
        if status == "ok":
            status = "partial"

    return SampleResult(
        status=status,
        requested_seconds=float(seconds),
        before=before,
        after=after,
        delta=_delta(before, after),
        codex_process_observed=(
            before_scan.codex_running or after_scan.codex_running
        ),
        target_open_by_codex=(
            database_path in before_scan.open_database_paths
            or database_path in after_scan.open_database_paths
        ),
        findings=tuple(findings),
    )
