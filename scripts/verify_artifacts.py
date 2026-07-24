#!/usr/bin/env python3
"""Prove that packaged Python modules match the current source bytes."""

from __future__ import annotations

import sys
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "codex_storage_doctor"
ZIPAPP = ROOT / "dist" / "codex-storage-doctor.pyz"
PROJECT_VERSION = tomllib.loads(
    (ROOT / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]
WHEEL = (
    ROOT
    / "dist"
    / f"codex_storage_doctor-{PROJECT_VERSION}-py3-none-any.whl"
)


def source_modules() -> dict[str, bytes]:
    return {
        path.relative_to(ROOT / "src").as_posix(): path.read_bytes()
        for path in sorted(PACKAGE.glob("*.py"))
    }


def verify_archive(path: Path) -> None:
    expected = source_modules()
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        packaged_modules = {
            name
            for name in names
            if name.startswith("codex_storage_doctor/") and name.endswith(".py")
        }
        if packaged_modules != set(expected):
            raise ValueError(f"{path.name}: packaged module inventory is stale")
        for name, source_bytes in expected.items():
            if archive.read(name) != source_bytes:
                raise ValueError(f"{path.name}: stale source bytes for {name}")
        if any("__pycache__" in name or name.endswith(".pyc") for name in names):
            raise ValueError(f"{path.name}: bytecode cache found")


def main() -> int:
    try:
        verify_archive(ZIPAPP)
        verify_archive(WHEEL)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"artifact verification failed: {error}", file=sys.stderr)
        return 1
    print("artifact verification: source bytes and module inventories match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
