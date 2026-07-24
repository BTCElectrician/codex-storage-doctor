"""Narrow, read-only parsing of Codex SQLite-home configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib


MAX_CONFIG_BYTES = 1024 * 1024


class ConfigReadError(ValueError):
    """A controlled configuration error that never includes file contents."""


@dataclass(frozen=True, slots=True)
class ConfiguredSQLiteHome:
    path: Path
    source: str
    profile: str | None = None
    selected_profile: bool = False


def _resolved_path(value: str, *, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.absolute()


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ConfigReadError("Codex configuration exceeds the safe size limit")
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except ConfigReadError:
        raise
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigReadError("Codex configuration could not be parsed safely") from error
    return value


def load_config_sqlite_homes(path: str | Path) -> tuple[ConfiguredSQLiteHome, ...]:
    """Read only ``sqlite_home`` and named-profile routing from one TOML file."""

    config_path = Path(path)
    data = _load_toml(config_path)
    results: list[ConfiguredSQLiteHome] = []
    selected = data.get("profile")
    selected_profile = selected if isinstance(selected, str) else None

    top_level = data.get("sqlite_home")
    if isinstance(top_level, str) and top_level.strip():
        results.append(
            ConfiguredSQLiteHome(
                path=_resolved_path(top_level, base=config_path.parent),
                source="config:top_level",
            )
        )

    profiles = data.get("profiles")
    if isinstance(profiles, dict):
        for profile_name in sorted(profiles):
            profile_data = profiles[profile_name]
            if not isinstance(profile_name, str) or not isinstance(profile_data, dict):
                continue
            sqlite_home = profile_data.get("sqlite_home")
            if not isinstance(sqlite_home, str) or not sqlite_home.strip():
                continue
            results.append(
                ConfiguredSQLiteHome(
                    path=_resolved_path(sqlite_home, base=config_path.parent),
                    source="config:profile",
                    profile=profile_name,
                    selected_profile=profile_name == selected_profile,
                )
            )

    return tuple(results)


def discover_config_sqlite_homes(
    codex_home: str | Path,
) -> tuple[ConfiguredSQLiteHome, ...]:
    """Inspect only allowlisted config files directly within a Codex home."""

    root = Path(codex_home)
    paths: list[Path] = []
    primary = root / "config.toml"
    if primary.is_file():
        paths.append(primary)
    try:
        paths.extend(
            candidate
            for candidate in sorted(root.glob("*.config.toml"), key=lambda item: item.name)
            if candidate.is_file() and candidate != primary
        )
    except OSError:
        return ()

    results: list[ConfiguredSQLiteHome] = []
    for config_path in paths:
        try:
            homes = load_config_sqlite_homes(config_path)
        except ConfigReadError:
            continue
        if config_path.name == "config.toml":
            results.extend(homes)
            continue
        stem = config_path.name[: -len(".config.toml")]
        for home in homes:
            if home.profile is None:
                results.append(
                    ConfiguredSQLiteHome(
                        path=home.path,
                        source="config_file:profile",
                        profile=stem,
                        selected_profile=False,
                    )
                )
            else:
                results.append(home)
    return tuple(results)
