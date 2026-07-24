"""Deterministic JSON output and restrictive artifact writes."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


class ArtifactReadError(Exception):
    """A requested JSON artifact could not be decoded as an object."""


def render_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def write_private_json(
    path: Path,
    value: Mapping[str, Any],
    *,
    overwrite: bool = False,
) -> Path:
    target = path.expanduser().resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing artifact: {target}")
    parent_existed = target.parent.exists()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not parent_existed:
        try:
            target.parent.chmod(0o700)
        except OSError:
            if os.name != "nt":
                raise
    fd, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary_path.chmod(0o600)
        except OSError:
            if os.name != "nt":
                raise
        if overwrite:
            temporary_path.replace(target)
        elif os.name == "nt":
            try:
                temporary_path.rename(target)
            except FileExistsError as error:
                raise FileExistsError(
                    f"refusing to overwrite existing artifact: {target}"
                ) from error
        else:
            try:
                os.link(temporary_path, target)
            except FileExistsError as error:
                raise FileExistsError(
                    f"refusing to overwrite existing artifact: {target}"
                ) from error
            temporary_path.unlink()
        try:
            target.chmod(0o600)
        except OSError:
            if os.name != "nt":
                raise
    except BaseException:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise
    return target


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.expanduser().open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ArtifactReadError(f"cannot read JSON artifact: {error}") from error
    if not isinstance(value, dict):
        raise ArtifactReadError("expected a JSON object artifact")
    return value
