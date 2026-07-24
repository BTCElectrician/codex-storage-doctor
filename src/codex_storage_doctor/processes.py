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
PROCESS_SCAN_TIMEOUT_SECONDS = 3.0


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
    *,
    allow_discovery: bool = True,
) -> tuple[Path, str] | None:
    key = _normalized(target)
    known = database_by_key.get(key)
    if known is not None:
        return known
    if not allow_discovery or not _LOG_DATABASE.fullmatch(target.name):
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


def _parse_lsof_holders(
    output: str,
    database_by_key: dict[str, tuple[Path, str]],
    *,
    allow_discovery: bool,
    require_target_match: bool,
) -> tuple[dict[int, dict[str, object]], bool]:
    """Parse machine fields strictly enough that corruption fails closed."""

    holders: dict[int, dict[str, object]] = {}
    current_pid: int | None = None
    current_record_saw_command = False
    current_record_saw_name = False
    current_record_matched_target = False
    malformed = False

    def finish_record() -> None:
        nonlocal malformed
        if current_pid is None:
            return
        if not current_record_saw_command:
            malformed = True
        if not current_record_saw_name:
            malformed = True
        if require_target_match and not current_record_matched_target:
            malformed = True

    for line in output.splitlines():
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p":
            finish_record()
            if not value.isdigit():
                malformed = True
                current_pid = None
                continue
            current_pid = int(value)
            current_record_saw_command = False
            current_record_saw_name = False
            current_record_matched_target = False
            holders.setdefault(
                current_pid,
                {"basename": "unknown", "open_ids": []},
            )
            continue
        if field not in {"c", "f", "n"} or current_pid is None or not value:
            malformed = True
            continue
        holder = holders[current_pid]
        if field == "c":
            holder["basename"] = Path(value).name
            current_record_saw_command = True
            continue
        if field == "f":
            continue
        current_record_saw_name = True
        match = _match_database(
            Path(value),
            database_by_key,
            allow_discovery=allow_discovery,
        )
        if match is None:
            if require_target_match:
                malformed = True
            continue
        _, report_id = match
        open_ids = holder["open_ids"]
        assert isinstance(open_ids, list)
        if report_id not in open_ids:
            open_ids.append(report_id)
        current_record_matched_target = True
    finish_record()
    return holders, malformed


def _scan_linux(
    database_paths: Sequence[Path],
    *,
    proc_root: Path,
    runner: Runner,
) -> ProcessScan:
    database_by_key = {
        _normalized(path): (path, f"database-{index:03d}")
        for index, path in enumerate(database_paths, start=1)
    }
    observations: list[ProcessObservation] = []
    open_paths: list[Path] = []
    held_paths: list[Path] = []
    findings: list[Finding] = []
    partial = False
    target_holders: dict[int, dict[str, object]] = {}

    if database_paths:
        try:
            holders = runner(
                [
                    "lsof",
                    "-w",
                    "-Fpcn",
                    "--",
                    *(str(path) for path in database_paths),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=PROCESS_SCAN_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            partial = True
        else:
            if (
                holders.returncode not in (0, 1)
                or bool(holders.stderr.strip())
                or (holders.returncode == 1 and bool(holders.stdout.strip()))
            ):
                partial = True
            parsed_holders, malformed = _parse_lsof_holders(
                holders.stdout,
                database_by_key,
                allow_discovery=False,
                require_target_match=True,
            )
            target_holders.update(parsed_holders)
            if malformed or (holders.returncode == 0 and not holders.stdout.strip()):
                partial = True

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

    get_effective_uid = getattr(os, "geteuid", None)
    current_uid = get_effective_uid() if callable(get_effective_uid) else None
    observed_pids: set[int] = set()
    for pid_directory in pid_directories:
        pid = int(pid_directory.name)
        try:
            if (
                current_uid is not None
                and pid_directory.stat().st_uid != current_uid
            ):
                continue
        except OSError:
            partial = True
            continue
        try:
            comm = (pid_directory / "comm").read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            if pid_directory.exists():
                partial = True
            continue
        executable_basename = Path(comm).name
        try:
            executable_basename = Path(
                os.readlink(pid_directory / "exe").removesuffix(" (deleted)")
            ).name or executable_basename
        except OSError:
            pass
        is_codex = _is_codex_executable(executable_basename)

        holder = target_holders.get(pid)
        open_ids = (
            list(holder["open_ids"])
            if holder is not None
            else []
        )
        if holder is not None:
            for report_id in open_ids:
                for matched_path, known_id in database_by_key.values():
                    if known_id != report_id:
                        continue
                    if matched_path not in held_paths:
                        held_paths.append(matched_path)
                    if is_codex and matched_path not in open_paths:
                        open_paths.append(matched_path)
                    break

        if is_codex:
            try:
                descriptors = sorted(
                    (pid_directory / "fd").iterdir(),
                    key=lambda path: (
                        int(path.name) if path.name.isdigit() else path.name
                    ),
                )
                for descriptor in descriptors:
                    try:
                        target = Path(
                            os.readlink(descriptor).removesuffix(" (deleted)")
                        )
                    except OSError:
                        if os.path.lexists(descriptor):
                            partial = True
                        continue
                    match = _match_database(
                        target,
                        database_by_key,
                        allow_discovery=True,
                    )
                    if match is None:
                        continue
                    matched_path, report_id = match
                    if report_id not in open_ids:
                        open_ids.append(report_id)
                    if matched_path not in held_paths:
                        held_paths.append(matched_path)
                    if matched_path not in open_paths:
                        open_paths.append(matched_path)
            except OSError:
                if pid_directory.exists():
                    partial = True

        if is_codex or open_ids:
            observed_pids.add(pid)
            observations.append(
                ProcessObservation(
                    pid=pid,
                    surface=(
                        _surface(executable_basename)
                        if is_codex
                        else "database-holder"
                    ),
                    executable_basename=executable_basename,
                    is_codex=is_codex,
                    open_database_ids=tuple(open_ids),
                    write_bytes=_parse_linux_write_bytes(pid_directory / "io"),
                )
            )

    for pid, holder in sorted(target_holders.items()):
        if pid in observed_pids:
            continue
        open_ids = tuple(holder["open_ids"])
        if not open_ids:
            continue
        basename = str(holder["basename"])
        is_codex = _is_codex_executable(basename)
        for report_id in open_ids:
            for matched_path, known_id in database_by_key.values():
                if known_id != report_id:
                    continue
                if matched_path not in held_paths:
                    held_paths.append(matched_path)
                if is_codex and matched_path not in open_paths:
                    open_paths.append(matched_path)
                break
        observations.append(
            ProcessObservation(
                pid=pid,
                surface=(
                    _surface(basename) if is_codex else "database-holder"
                ),
                executable_basename=basename,
                is_codex=is_codex,
                open_database_ids=open_ids,
            )
        )

    if partial:
        findings.append(
            Finding(
                code="process_handle_evidence_partial",
                message=(
                    "Open-file evidence was incomplete for Codex discovery or "
                    "the selected database."
                ),
                severity=FindingSeverity.WARNING,
                partial=True,
            )
        )
    return ProcessScan(
        status="partial" if partial else "ok",
        observations=tuple(observations),
        open_database_paths=tuple(open_paths),
        held_database_paths=tuple(held_paths),
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
            timeout=PROCESS_SCAN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
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
    if result.returncode != 0 or bool(result.stderr.strip()):
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
    observation_data: dict[int, dict[str, object]] = {}
    open_paths: list[Path] = []
    held_paths: list[Path] = []
    partial = False

    def observe(
        pid: int,
        basename: str,
        *,
        is_codex: bool,
        report_id: str | None = None,
    ) -> None:
        data = observation_data.setdefault(
            pid,
            {
                "basename": basename,
                "is_codex": is_codex,
                "open_ids": [],
            },
        )
        if is_codex:
            data["is_codex"] = True
            data["basename"] = basename
        open_ids = data["open_ids"]
        assert isinstance(open_ids, list)
        if report_id is not None and report_id not in open_ids:
            open_ids.append(report_id)

    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_value, separator, executable = stripped.partition(" ")
        if not separator or not pid_value.isdigit():
            partial = True
            continue
        basename = Path(executable.strip()).name
        if not basename:
            partial = True
            continue
        if not _is_codex_executable(basename):
            continue

        pid = int(pid_value)
        observe(pid, basename, is_codex=True)
        try:
            handles = runner(
                ["lsof", "-w", "-Fpcn", "-p", pid_value],
                capture_output=True,
                text=True,
                check=False,
                timeout=PROCESS_SCAN_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            partial = True
        else:
            if (
                handles.returncode not in (0, 1)
                or bool(handles.stderr.strip())
                or (handles.returncode == 1 and bool(handles.stdout.strip()))
            ):
                partial = True
            parsed_holders, malformed = _parse_lsof_holders(
                handles.stdout,
                database_by_key,
                allow_discovery=True,
                require_target_match=False,
            )
            if malformed or (
                handles.returncode == 0 and not handles.stdout.strip()
            ):
                partial = True
            for holder in parsed_holders.values():
                open_ids = holder["open_ids"]
                assert isinstance(open_ids, list)
                for report_id in open_ids:
                    observe(pid, basename, is_codex=True, report_id=report_id)
                    for matched_path, known_id in database_by_key.values():
                        if known_id != report_id:
                            continue
                        if matched_path not in held_paths:
                            held_paths.append(matched_path)
                        if matched_path not in open_paths:
                            open_paths.append(matched_path)
                        break

    if database_paths:
        try:
            holders = runner(
                [
                    "lsof",
                    "-w",
                    "-Fpcn",
                    "--",
                    *(str(path) for path in database_paths),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=PROCESS_SCAN_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            partial = True
        else:
            if (
                holders.returncode not in (0, 1)
                or bool(holders.stderr.strip())
                or (holders.returncode == 1 and bool(holders.stdout.strip()))
            ):
                partial = True
            parsed_holders, malformed = _parse_lsof_holders(
                holders.stdout,
                database_by_key,
                allow_discovery=False,
                require_target_match=True,
            )
            if malformed or (
                holders.returncode == 0 and not holders.stdout.strip()
            ):
                partial = True
            for current_pid, holder in parsed_holders.items():
                basename = str(holder["basename"])
                is_codex = _is_codex_executable(basename)
                open_ids = holder["open_ids"]
                assert isinstance(open_ids, list)
                for report_id in open_ids:
                    observe(
                        current_pid,
                        basename,
                        is_codex=is_codex,
                        report_id=report_id,
                    )
                    for matched_path, known_id in database_by_key.values():
                        if known_id != report_id:
                            continue
                        if matched_path not in held_paths:
                            held_paths.append(matched_path)
                        if is_codex and matched_path not in open_paths:
                            open_paths.append(matched_path)
                        break

    findings: tuple[Finding, ...] = ()
    if partial:
        findings = (
            Finding(
                code="process_handle_evidence_partial",
                message=(
                    "Open-file evidence was incomplete for Codex discovery or "
                    "the selected database."
                ),
                severity=FindingSeverity.WARNING,
                partial=True,
            ),
        )
    observations = tuple(
        ProcessObservation(
            pid=pid,
            surface=(
                _surface(str(data["basename"]))
                if bool(data["is_codex"])
                else "database-holder"
            ),
            executable_basename=str(data["basename"]),
            is_codex=bool(data["is_codex"]),
            open_database_ids=tuple(data["open_ids"]),  # type: ignore[arg-type]
        )
        for pid, data in sorted(observation_data.items())
    )
    return ProcessScan(
        status="partial" if partial else "ok",
        observations=observations,
        open_database_paths=tuple(open_paths),
        held_database_paths=tuple(held_paths),
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
            timeout=PROCESS_SCAN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if (
        result is None
        or result.returncode != 0
        or bool(result.stderr.strip())
    ):
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
        return _scan_linux(
            paths,
            proc_root=Path(proc_root),
            runner=runner_value,
        )
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
