"""Deterministic, bounded discovery of Codex diagnostic databases."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path, PureWindowsPath
import re
import sys
from typing import Iterable, Mapping

from .config import ConfiguredSQLiteHome, discover_config_sqlite_homes
from .models import DatabaseCandidate, assign_candidate_report_ids


KNOWN_DATABASE_FILENAME = "logs_2.sqlite"
DATABASE_PATTERN = "logs_*.sqlite"
_WSL_MOUNTED_WINDOWS = re.compile(r"^/mnt/[a-z](?:/|$)", re.IGNORECASE)


def _absolute(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().absolute()


def _database_files(root: Path) -> tuple[Path, ...]:
    if root.is_file():
        return (root,) if root.name.startswith("logs_") and root.suffix == ".sqlite" else ()
    if not root.is_dir():
        return ()
    try:
        return tuple(
            sorted(
                (path for path in root.glob(DATABASE_PATTERN) if path.is_file()),
                key=lambda path: (path.name != KNOWN_DATABASE_FILENAME, path.name),
            )
        )
    except OSError:
        return ()


def _is_windows(platform_name: str) -> bool:
    return platform_name.lower().startswith(("win", "cygwin"))


def _is_wsl(environ: Mapping[str, str]) -> bool:
    return bool(environ.get("WSL_DISTRO_NAME") or environ.get("WSL_INTEROP"))


def is_cross_boundary_path(
    path: str | os.PathLike[str],
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Return whether mutation should be handed to the path's native side."""

    platform_value = sys.platform if platform_name is None else platform_name
    env = os.environ if environ is None else environ
    value = str(path).replace("\\", "/")
    if _is_windows(platform_value):
        lowered = value.lower()
        return lowered.startswith("//wsl$/") or lowered.startswith("//wsl.localhost/")
    if platform_value.lower().startswith("linux") and _is_wsl(env):
        return bool(_WSL_MOUNTED_WINDOWS.match(value))
    return False


def _wsl_windows_home(environ: Mapping[str, str]) -> Path | None:
    user_profile = environ.get("USERPROFILE")
    if not user_profile:
        return None
    if user_profile.startswith("/"):
        return Path(user_profile)
    windows_path = PureWindowsPath(user_profile)
    drive = windows_path.drive.rstrip(":").lower()
    if len(drive) != 1 or not windows_path.parts:
        return None
    tail = windows_path.parts[1:]
    return Path("/mnt") / drive / Path(*tail)


def _candidate_roots(
    *,
    explicit_codex_homes: Iterable[str | os.PathLike[str]],
    explicit_sqlite_homes: Iterable[str | os.PathLike[str]],
    environ: Mapping[str, str],
    home: Path,
    platform_name: str,
) -> tuple[tuple[Path, str, bool, str], ...]:
    """Return ``(root, source, configured_current, forced_cross_boundary)``."""

    roots: list[tuple[Path, str, bool, str]] = []
    explicit_codex = tuple(_absolute(value) for value in explicit_codex_homes)
    explicit_sqlite = tuple(_absolute(value) for value in explicit_sqlite_homes)

    roots.extend(
        (path, "explicit:sqlite_home", False, "") for path in explicit_sqlite
    )
    roots.extend((path, "explicit:codex_home", False, "") for path in explicit_codex)

    env_codex = environ.get("CODEX_HOME")
    default_codex_home = home / ".codex"
    config_roots: list[tuple[Path, bool]] = [
        (path, False) for path in explicit_codex
    ]
    if env_codex:
        config_roots.append((_absolute(env_codex), True))
        config_roots.append((default_codex_home, False))
    else:
        config_roots.append((default_codex_home, True))

    seen_config_roots: dict[str, int] = {}
    unique_config_roots: list[tuple[Path, bool]] = []
    for config_root, effective in config_roots:
        key = os.path.normcase(str(config_root))
        existing = seen_config_roots.get(key)
        if existing is not None:
            if effective:
                unique_config_roots[existing] = (config_root, True)
            continue
        seen_config_roots[key] = len(unique_config_roots)
        unique_config_roots.append((config_root, effective))

    configured_homes: list[tuple[ConfiguredSQLiteHome, bool]] = []
    for config_root, effective in unique_config_roots:
        configured_homes.extend(
            (configured, effective)
            for configured in discover_config_sqlite_homes(config_root)
        )

    effective_configured = [
        configured for configured, effective in configured_homes if effective
    ]
    selected_profiles = {
        configured.profile
        for configured in effective_configured
        if configured.selected_profile
    }
    has_current_config = bool(effective_configured)
    env_sqlite = environ.get("CODEX_SQLITE_HOME")
    if env_sqlite:
        roots.append(
            (
                _absolute(env_sqlite),
                "environment:CODEX_SQLITE_HOME",
                not has_current_config,
                "",
            )
        )
    if env_codex:
        roots.append(
            (
                _absolute(env_codex),
                "environment:CODEX_HOME",
                not has_current_config and not env_sqlite,
                "",
            )
        )

    for configured, effective in configured_homes:
        if selected_profiles:
            is_current = effective and configured.profile in selected_profiles
        else:
            is_current = effective and configured.profile is None
        roots.append((configured.path, configured.source, is_current, ""))

    roots.append(
        (
            default_codex_home,
            "platform:default",
            not has_current_config and not env_sqlite and not env_codex,
            "",
        )
    )

    if platform_name.lower().startswith("linux") and _is_wsl(environ):
        windows_home = _wsl_windows_home(environ)
        if windows_home is not None:
            roots.append(
                (
                    windows_home / ".codex",
                    "platform:wsl_windows_default",
                    False,
                    "cross_boundary",
                )
            )
    return tuple(roots)


def discover_candidates(
    explicit_codex_homes: Iterable[str | os.PathLike[str]] = (),
    explicit_sqlite_homes: Iterable[str | os.PathLike[str]] = (),
    environ: Mapping[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
    platform_name: str | None = None,
) -> list[DatabaseCandidate]:
    """Discover existing ``logs_*.sqlite`` files without recursive disk search."""

    env = dict(os.environ if environ is None else environ)
    platform_value = sys.platform if platform_name is None else platform_name
    home_path = _absolute(Path.home() if home is None else home)
    roots = _candidate_roots(
        explicit_codex_homes=explicit_codex_homes,
        explicit_sqlite_homes=explicit_sqlite_homes,
        environ=env,
        home=home_path,
        platform_name=platform_value,
    )

    ordered_paths: list[Path] = []
    metadata: dict[str, dict[str, object]] = {}
    for root, source, configured_current, forced_cross in roots:
        for database_path in _database_files(root):
            absolute_path = database_path.absolute()
            key_value = os.path.normcase(str(absolute_path))
            if _is_windows(platform_value):
                key_value = key_value.casefold()
            info = metadata.get(key_value)
            cross_boundary = forced_cross == "cross_boundary" or is_cross_boundary_path(
                absolute_path, platform_name=platform_value, environ=env
            )
            if info is None:
                ordered_paths.append(absolute_path)
                info = {
                    "sources": [],
                    "labels": [],
                    "cross_boundary": cross_boundary,
                }
                metadata[key_value] = info
            source_values = info["sources"]
            label_values = info["labels"]
            assert isinstance(source_values, list)
            assert isinstance(label_values, list)
            if source not in source_values:
                source_values.append(source)
            if source.startswith("explicit:"):
                label = "explicit_selection"
            elif configured_current:
                label = "configured_current"
            elif source.startswith(("config:", "config_file:")):
                label = "configured_profile"
            else:
                label = ""
            if label and label not in label_values:
                label_values.append(label)
            info["cross_boundary"] = bool(info["cross_boundary"]) or cross_boundary

    candidates: list[DatabaseCandidate] = []
    for database_path in ordered_paths:
        key_value = os.path.normcase(str(database_path))
        if _is_windows(platform_value):
            key_value = key_value.casefold()
        info = metadata[key_value]
        cross_boundary = bool(info["cross_boundary"])
        candidates.append(
            DatabaseCandidate(
                path=database_path,
                report_id="",
                sources=tuple(info["sources"]),  # type: ignore[arg-type]
                exists=True,
                known_filename=database_path.name == KNOWN_DATABASE_FILENAME,
                evidence_labels=tuple(info["labels"]),  # type: ignore[arg-type]
                mutation_allowed=not cross_boundary,
                refusal_reason=(
                    "Run mutation commands on the database's native OS side."
                    if cross_boundary
                    else None
                ),
            )
        )
    return list(assign_candidate_report_ids(candidates))


def classify_candidate_activity(
    candidates: Iterable[DatabaseCandidate],
    *,
    open_paths: Iterable[str | os.PathLike[str]] = (),
    changed_paths: Iterable[str | os.PathLike[str]] = (),
) -> tuple[DatabaseCandidate, ...]:
    """Add direct activity labels and conservatively identify stale duplicates."""

    open_keys = {os.path.normcase(str(_absolute(path))) for path in open_paths}
    changed_keys = {os.path.normcase(str(_absolute(path))) for path in changed_paths}
    values = list(candidates)
    directly_active = open_keys | changed_keys
    active_mtimes: list[int] = []
    for candidate in values:
        key = os.path.normcase(str(candidate.path.absolute()))
        if key not in directly_active:
            continue
        try:
            active_mtimes.append(candidate.path.stat().st_mtime_ns)
        except OSError:
            pass
    newest_direct_activity = max(active_mtimes, default=None)
    results: list[DatabaseCandidate] = []
    for candidate in values:
        key = os.path.normcase(str(candidate.path.absolute()))
        labels = list(candidate.evidence_labels)
        if key in open_keys and "open_by_codex_process" not in labels:
            labels.append("open_by_codex_process")
        if key in changed_keys and "changed_during_sample" not in labels:
            labels.append("changed_during_sample")
        if newest_direct_activity is not None and key not in directly_active:
            try:
                candidate_mtime = candidate.path.stat().st_mtime_ns
            except OSError:
                candidate_mtime = None
            if (
                candidate_mtime is not None
                and candidate_mtime < newest_direct_activity
                and "stale_duplicate" not in labels
            ):
                labels.append("stale_duplicate")
        if not labels:
            labels.append("unknown")
        results.append(replace(candidate, evidence_labels=tuple(labels)))
    return tuple(results)
