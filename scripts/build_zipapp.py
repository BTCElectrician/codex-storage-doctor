#!/usr/bin/env python3
"""Build the dependency-free Codex Storage Doctor zipapp."""

from __future__ import annotations

import argparse
import shutil
import tempfile
import zipapp
from pathlib import Path


def build(output: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    source = root / "src"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-storage-doctor-zipapp-") as tmp:
        stage = Path(tmp)
        shutil.copytree(
            source / "codex_storage_doctor",
            stage / "codex_storage_doctor",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        zipapp.create_archive(
            stage,
            target=output,
            main="codex_storage_doctor.cli:main",
            interpreter="/usr/bin/env python3",
            compressed=True,
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/codex-storage-doctor.pyz"),
    )
    args = parser.parse_args()
    print(build(args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
