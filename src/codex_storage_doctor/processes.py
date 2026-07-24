"""Best-effort process and open-handle evidence without command arguments."""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
from typing import Callable, Iterable, Protocol, Sequence

from .models import Finding, FindingSeverity, ProcessObservation, ProcessScan


class ProcessAdapter(Protocol):
    def scan(self, database_paths: Sequence[Path]) -> ProcessScan: ...


Runner = Callable[..., subprocess.CompletedProcess[str]]
_LOG_DATABASE = re.compile(r"^logs_[0-9]+\.sqlite$", re.IGNORECASE)


def _normalized(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve(strict=False)))
    except OSError:
        return os.path.normcase(str(path.absolute()))


def _surface(executable_basename: str) -> str:
    lowered = executable_basename.lower()
    if "codex" in lowered and lowered.endswith(".exe"):
        return "codex-windows"
    if "codex" in lowered:
        return "codex"
    return "codex-related"


def _is_codex_executable(executable_basename: str) -> bool:
    return "codex" in executable_basename.lower()


def _match_database(
    target: Path,
    database_by_key: dict[str, tuple[Path, str]],
) -> tuple[Path, str] | None:
    key = _normalized(target)
    known = database_by_key.get(key)
    if known is not None:
        return known
    if not _LOG_DATABASE.fullmatch(target.name):
        return None
    discovered = target.absolute()
    result = (discovered, f"database-{len(database_by_key) + 1:03d}")
    database_by_key[key] = result
    return result


def _parse_linux_write_bytes(io_path: Path) -> int | None:
    try:
        for line in io_path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() == "write_bytes":
                return int(value.strip())
    except (OSError, ValueError):
        return None
    return None


def _scan_linux(database_paths: Sequence[Path], *, proc_root: Path) -> ProcessScan:
    database_by_key = {
        _normalized(path): (path, f"database-{index:03d}")
        for index, path in enumerate(database_paths, start=1)
    }
    observations: list[ProcessObservation] = []
    open_paths: list[Path] = []
    findings: list[Finding] = []
    partial = False

    try:
        pid_directories = sorted(
            (path for path in proc_root.iterdir() if path.name.isdigit()),
            key=lambda path: int(path.name),
        )
    except OSError:
        return ProcessScan(
            status="partial",
            handle_evidence_supported=False,
            findings=(
                Finding(
                    code="process_scan_unavailable",
                    message="The process filesystem could not be inspected.",
                    severity=FindingSeverity.WARNING,
                    partial=True,
                ),
            ),
        )

    for pid_directory in pid_directories:
        try:
            comm = (pid_directory / "comm").read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            # Process exit and permission races are ordinary during enumeration.
            continue
        executable_basename = Path(comm).name
        try:
            executable_basename = Path(
                os.readlink(pid_directory / "exe").removesuffix(" (deleted)")
            ).name or executable_basename
        except OSError:
            pass
        if not _is_codex_executable(executable_basename):
            continue

        open_ids: list[str] = []
        try:
            descriptors = sorted(
                (pid_directory / "fd").iterdir(),
                key=lambda path: int(path.name) if path.name.isdigit() else path.name,
            )
            for descriptor in descriptors:
                try:
                    target = Path(
                        os.readlink(descriptor).removesuffix(" (deleted)")
                    )
                except OSError:
                    continue
                match = _match_database(target, database_by_key)
                if match is None:
                    continue
                matched_path, report_id = match
                if report_id not in open_ids:
                    open_ids.append(report_id)
                if matched_path not in open_paths:
                    open_paths.append(matched_path)
        except OSError:
            partial = True

        observations.append(
            ProcessObservation(
                pid=int(pid_directory.name),
                surface=_surface(executable_basename),
                executable_basename=executable_basename,
                open_database_ids=tuple(open_ids),
                write_bytes=_parse_linux_write_bytes(pid_directory / "io"),
            )
        )

    if partial:
        findings.append(
            Finding(
                code="process_handle_evidence_partial",
                message="At least one Codex process handle set could not be inspected.",
                severity=FindingSeverity.WARNING,
                partial=True,
            )
        )
    return ProcessScan(
        status="partial" if partial else "ok",
        observations=tuple(observations),
        open_database_paths=tuple(open_paths),
        handle_evidence_supported=not partial,
        findings=tuple(findings),
    )


def _default_runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(*args, **kwargs)  # type: ignore[arg-type]


def _scan_macos(
    database_paths: Sequence[Path],
    *,
    runner: Runner,
) -> ProcessScan:
    try:
        result = runner(
            ["ps", "-axo", "pid=,comm="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ProcessScan(
            status="partial",
            handle_evidence_supported=False,
            findings=(
                Finding(
                    code="process_scan_unavailable",
                    message="The macOS process list could not be inspected.",
                    severity=FindingSeverity.WARNING,
                    partial=True,
                ),
            ),
        )
    if result.returncode != 0:
        return ProcessScan(
            status="partial",
            handle_evidence_supported=False,
            findings=(
                Finding(
                    code="process_scan_unavailable",
                    message="The macOS process list could not be inspected.",
                    severity=FindingSeverity.WARNING,
                    partial=True,
                ),
            ),
        )

    database_by_key = {
        _normalized(path): (path, f"database-{index:03d}")
        for index, path in enumerate(database_paths, start=1)
    }
    observations: list[ProcessObservation] = []
    open_paths: list[Path] = []
    partial = False
    for line in result.stdout.splitlines():
        pid_value, separator, executable = line.strip().partition(" ")
        if not separator or not pid_value.isdigit():
            continue
        basename = Path(executable.strip()).name
        if not _is_codex_executable(basename):
            continue

        open_ids: list[str] = []
        try:
            handles = runner(
                ["lsof", "-Fn", "-p", pid_value],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            partial = True
        else:
            if handles.returncode not in (0, 1):
                partial = True
            for handle_line in handles.stdout.splitlines():
                if not handle_line.startswith("n"):
                    continue
                match = _match_database(Path(handle_line[1:]), database_by_key)
                if match is None:
                    continue
                matched_path, report_id = match
                if report_id not in open_ids:
                    open_ids.append(report_id)
                if matched_path not in open_paths:
                    open_paths.append(matched_path)

        observations.append(
            ProcessObservation(
                pid=int(pid_value),
                surface=_surface(basename),
                executable_basename=basename,
                open_database_ids=tuple(open_ids),
            )
        )

    findings: tuple[Finding, ...] = ()
    if partial:
        findings = (
            Finding(
                code="process_handle_evidence_partial",
                message="Open-file evidence was incomplete for a Codex process.",
                severity=FindingSeverity.WARNING,
                partial=True,
            ),
        )
    return ProcessScan(
        status="partial" if partial else "ok",
        observations=tuple(observations),
        open_database_paths=tuple(open_paths),
        handle_evidence_supported=not partial,
        findings=findings,
    )


def _scan_windows(
    database_paths: Sequence[Path],
    *,
    runner: Runner,
) -> ProcessScan:
    del database_paths  # Standard-library Windows handle enumeration is unavailable.
    script = (
        "Get-Process | Where-Object { $_.ProcessName -like '*codex*' } | "
        "Select-Object Id,ProcessName,Path | ConvertTo-Json -Compress"
    )
    try:
        result = runner(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        result = None
    if result is None or result.returncode != 0:
        return ProcessScan(
            status="partial",
            handle_evidence_supported=False,
            findings=(
                Finding(
                    code="process_scan_unavailable",
                    message="The Windows process list could not be inspected.",
                    severity=FindingSeverity.WARNING,
                    partial=True,
                ),
            ),
        )
    try:
        payload = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        payload = None
    if payload is None:
        return ProcessScan(
            status="partial",
            handle_evidence_supported=False,
            findings=(
                Finding(
                    code="process_scan_unavailable",
                    message="The Windows process result could not be interpreted.",
                    severity=FindingSeverity.WARNING,
                    partial=True,
                ),
            ),
        )
    rows = payload if isinstance(payload, list) else [payload]
    observations: list[ProcessObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = row.get("Id")
        process_name = row.get("ProcessName")
        executable_path = row.get("Path")
        if not isinstance(pid, int) or not isinstance(process_name, str):
            continue
        basename = (
            PureWindowsPath(executable_path).name
            if isinstance(executable_path, str) and executable_path
            else f"{process_name}.exe"
        )
        if not _is_codex_executable(basename):
            continue
        observations.append(
            ProcessObservation(
                pid=pid,
                surface=_surface(basename),
                executable_basename=basename,
            )
        )
    return ProcessScan(
        status="partial",
        observations=tuple(sorted(observations, key=lambda item: item.pid)),
        handle_evidence_supported=False,
        findings=(
            Finding(
                code="windows_handle_evidence_unsupported",
                message=(
                    "Windows open-database handle evidence is unavailable without "
                    "additional platform tooling."
                ),
                severity=FindingSeverity.WARNING,
                partial=True,
            ),
        ),
    )


def scan_codex_processes(
    database_paths: Iterable[str | os.PathLike[str]] = (),
    platform_name: str | None = None,
    *,
    adapter: ProcessAdapter | Callable[[Sequence[Path]], ProcessScan] | None = None,
    proc_root: str | os.PathLike[str] = "/proc",
    runner: Runner | None = None,
) -> ProcessScan:
    """Return process presence and handle evidence without outputting arguments."""

    paths = tuple(Path(path).absolute() for path in database_paths)
    if adapter is not None:
        scan = getattr(adapter, "scan", None)
        return scan(paths) if callable(scan) else adapter(paths)  # type: ignore[misc]

    platform_value = sys.platform if platform_name is None else platform_name
    runner_value = _default_runner if runner is None else runner
    if platform_value.lower().startswith("linux"):
        return _scan_linux(paths, proc_root=Path(proc_root))
    if platform_value.lower().startswith("darwin"):
        return _scan_macos(paths, runner=runner_value)
    if platform_value.lower().startswith(("win", "cygwin")):
        return _scan_windows(paths, runner=runner_value)
    return ProcessScan(
        status="unsupported",
        handle_evidence_supported=False,
        findings=(
            Finding(
                code="platform_process_scan_unsupported",
                message="Process evidence is unsupported on this platform.",
                severity=FindingSeverity.WARNING,
                partial=True,
            ),
        ),
    )
