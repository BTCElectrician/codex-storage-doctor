#!/usr/bin/env python3
"""Build a wheel from a fresh staged source tree."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def build(output_directory: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    destination = output_directory.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="codex-storage-doctor-wheel-"
    ) as temporary:
        workspace = Path(temporary)
        stage = workspace / "source"
        stage.mkdir()
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            shutil.copy2(root / name, stage / name)
        shutil.copytree(
            root / "src",
            stage / "src",
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                "*.pyo",
                "*.egg-info",
            ),
        )
        built = workspace / "dist"
        environment = dict(os.environ)
        environment["PIP_NO_INDEX"] = "1"
        environment["PYTHONHASHSEED"] = "0"
        environment["SOURCE_DATE_EPOCH"] = "315532800"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "--disable-pip-version-check",
                "wheel",
                str(stage),
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(built),
            ],
            check=True,
            env=environment,
        )
        wheels = tuple(built.glob("codex_storage_doctor-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("wheel build did not produce exactly one artifact")
        target = destination / wheels[0].name
        staged_target = target.with_suffix(target.suffix + ".tmp")
        if staged_target.exists():
            raise FileExistsError(
                f"refusing to overwrite temporary artifact: {staged_target}"
            )
        shutil.copy2(wheels[0], staged_target)
        staged_target.replace(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("dist"),
    )
    args = parser.parse_args()
    print(build(args.output_directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
