"""Small, privacy-bounded models shared by the doctor.

The objects in this module may retain a local ``Path`` for internal operations.
Their default serializers deliberately replace it with a report-local ID.
They never have fields for diagnostic bodies, targets, thread identifiers,
process UUIDs, modules, source files, or command arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable


KNOWN_LEVELS: tuple[str, ...] = ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "OTHER")


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    message: str
    severity: FindingSeverity = FindingSeverity.INFO
    partial: bool = False

    def to_dict(self) -> dict[str, Any]:
        # "detail" is intentionally controlled prose, never a raw exception.
        return {
            "code": self.code,
            "detail": self.message,
            "severity": self.severity.value,
            "partial": self.partial,
        }


@dataclass(frozen=True, slots=True)
class DatabaseCandidate:
    path: Path
    report_id: str
    sources: tuple[str, ...]
    exists: bool = True
    known_filename: bool = False
    evidence_labels: tuple[str, ...] = ()
    mutation_allowed: bool = True
    refusal_reason: str | None = None

    def to_dict(self, *, reveal_paths: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.report_id,
            "sources": list(self.sources),
            "exists": self.exists,
            "known_filename": self.known_filename,
            "evidence_labels": list(self.evidence_labels),
            "mutation_allowed": self.mutation_allowed,
            "refusal_reason": self.refusal_reason,
        }
        if reveal_paths:
            result["revealed_path"] = str(self.path)
        return result


def assign_candidate_report_ids(
    candidates: Iterable[DatabaseCandidate],
) -> tuple[DatabaseCandidate, ...]:
    """Assign deterministic report-local IDs without hashing a local path."""

    return tuple(
        replace(candidate, report_id=f"database-{index:03d}")
        for index, candidate in enumerate(candidates, start=1)
    )


@dataclass(frozen=True, slots=True)
class ProcessObservation:
    pid: int
    surface: str
    executable_basename: str
    open_database_ids: tuple[str, ...] = ()
    write_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "surface": self.surface,
            "executable_basename": self.executable_basename,
            "open_database_ids": list(self.open_database_ids),
            "write_bytes": self.write_bytes,
        }


@dataclass(frozen=True, slots=True)
class ProcessScan:
    status: str
    observations: tuple[ProcessObservation, ...] = ()
    open_database_paths: tuple[Path, ...] = field(default=(), repr=False)
    handle_evidence_supported: bool = True
    findings: tuple[Finding, ...] = ()

    @property
    def codex_running(self) -> bool:
        return bool(self.observations)

    @property
    def total_write_bytes(self) -> int | None:
        values = [
            observation.write_bytes
            for observation in self.observations
            if observation.write_bytes is not None
        ]
        return sum(values) if values else None

    def to_dict(self) -> dict[str, Any]:
        open_database_ids = sorted(
            {
                report_id
                for observation in self.observations
                for report_id in observation.open_database_ids
            }
        )
        if self.open_database_paths and not open_database_ids:
            # Preserve the fail-closed truth for internal safety gates without
            # serializing an absolute local path.
            open_database_ids = [
                f"open-database-{index:03d}"
                for index, _ in enumerate(self.open_database_paths, start=1)
            ]
        return {
            "status": self.status,
            "complete": self.status == "ok" and self.handle_evidence_supported,
            "codex_running": self.codex_running,
            "handle_evidence_supported": self.handle_evidence_supported,
            "observations": [
                observation.to_dict() for observation in self.observations
            ],
            # Compatibility keys are intentionally privacy-safe. Mutation gates
            # need only their truthiness.
            "processes": [
                observation.to_dict() for observation in self.observations
            ],
            "open_database_paths": open_database_ids,
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True, slots=True)
class SchemaColumn:
    name: str
    declared_type: str
    not_null: bool
    primary_key_position: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "declared_type": self.declared_type,
            "not_null": self.not_null,
            "primary_key_position": self.primary_key_position,
        }


@dataclass(frozen=True, slots=True)
class LevelAggregate:
    level: str
    rows: int
    estimated_bytes: int | float

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "rows": self.rows,
            "estimated_bytes": self.estimated_bytes,
        }


@dataclass(frozen=True, slots=True)
class DatabaseInspection:
    path: Path = field(repr=False)
    status: str = "ok"
    exists: bool = True
    database_size_bytes: int = 0
    wal_size_bytes: int = 0
    shm_size_bytes: int = 0
    quick_check_ok: bool | None = None
    schema_supported: bool = False
    schema_columns: tuple[SchemaColumn, ...] = ()
    doctor_triggers: tuple[str, ...] = ()
    altered_doctor_triggers: tuple[str, ...] = ()
    full_scan_performed: bool = False
    row_count: int | None = None
    max_id: int | None = None
    sqlite_sequence: int | None = None
    estimated_bytes: int | float | None = None
    level_aggregates: tuple[LevelAggregate, ...] = ()
    findings: tuple[Finding, ...] = ()
    report_id: str = "database"

    @property
    def partial(self) -> bool:
        return self.status == "partial" or any(finding.partial for finding in self.findings)

    def to_dict(self, *, reveal_paths: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.report_id,
            "status": self.status,
            "partial": self.partial,
            "exists": self.exists,
            "database_size_bytes": self.database_size_bytes,
            "wal_size_bytes": self.wal_size_bytes,
            "shm_size_bytes": self.shm_size_bytes,
            "quick_check_ok": self.quick_check_ok,
            "schema_supported": self.schema_supported,
            "schema_columns": [column.to_dict() for column in self.schema_columns],
            "doctor_triggers": list(self.doctor_triggers),
            "altered_doctor_triggers": list(self.altered_doctor_triggers),
            "full_scan_performed": self.full_scan_performed,
            "row_count": self.row_count,
            "max_id": self.max_id,
            "sqlite_sequence": self.sqlite_sequence,
            "estimated_bytes": self.estimated_bytes,
            "level_aggregates": [
                aggregate.to_dict() for aggregate in self.level_aggregates
            ],
            "findings": [finding.to_dict() for finding in self.findings],
        }
        if reveal_paths:
            result["revealed_path"] = str(self.path)
        return result


@dataclass(frozen=True, slots=True)
class LogicalSnapshot:
    database_size_bytes: int
    wal_size_bytes: int
    shm_size_bytes: int
    row_count: int | None
    max_id: int | None
    sqlite_sequence: int | None
    estimated_bytes: int | float | None
    levels: tuple[LevelAggregate, ...]
    process_write_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "database_size_bytes": self.database_size_bytes,
            "wal_size_bytes": self.wal_size_bytes,
            "shm_size_bytes": self.shm_size_bytes,
            "row_count": self.row_count,
            "max_id": self.max_id,
            "sqlite_sequence": self.sqlite_sequence,
            "estimated_bytes": self.estimated_bytes,
            "levels": [level.to_dict() for level in self.levels],
            "process_write_bytes": self.process_write_bytes,
        }


@dataclass(frozen=True, slots=True)
class SampleDelta:
    database_size_bytes: int
    wal_size_bytes: int
    shm_size_bytes: int
    row_count: int | None
    max_id: int | None
    sqlite_sequence: int | None
    estimated_bytes: int | float | None
    levels: tuple[LevelAggregate, ...]
    process_write_bytes: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "database_size_bytes": self.database_size_bytes,
            "wal_size_bytes": self.wal_size_bytes,
            "shm_size_bytes": self.shm_size_bytes,
            "row_count": self.row_count,
            "max_id": self.max_id,
            "sqlite_sequence": self.sqlite_sequence,
            "estimated_bytes": self.estimated_bytes,
            "levels": [level.to_dict() for level in self.levels],
            "process_write_bytes": self.process_write_bytes,
        }


@dataclass(frozen=True, slots=True)
class SampleResult:
    status: str
    requested_seconds: float
    before: LogicalSnapshot
    after: LogicalSnapshot
    delta: SampleDelta
    codex_process_observed: bool
    target_open_by_codex: bool
    findings: tuple[Finding, ...] = ()

    @property
    def logical_change_observed(self) -> bool:
        delta = self.delta
        scalar_values = (
            delta.database_size_bytes,
            delta.wal_size_bytes,
            delta.row_count,
            delta.max_id,
            delta.sqlite_sequence,
            delta.estimated_bytes,
        )
        return any(value not in (None, 0) for value in scalar_values) or any(
            level.rows != 0 or level.estimated_bytes != 0 for level in delta.levels
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "requested_seconds": self.requested_seconds,
            "codex_process_observed": self.codex_process_observed,
            "target_open_by_codex": self.target_open_by_codex,
            "logical_change_observed": self.logical_change_observed,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "delta": self.delta.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
            "bounded_observation": (
                "This sample reports only changes observed during the bounded "
                "interval. It does not measure physical drive writes."
            ),
        }
