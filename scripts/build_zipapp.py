#!/usr/bin/env python3
"""Build the dependency-free Codex Storage Doctor zipapp."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import zipapp
import zipfile
from pathlib import Path


_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_MAIN = (
    b"# -*- coding: utf-8 -*-\n"
    b"import codex_storage_doctor.cli\n"
    b"raise SystemExit(codex_storage_doctor.cli.main())\n"
)


def _write_reproducible_archive(stage: Path, output: Path) -> None:
    with output.open("wb") as stream:
        stream.write(b"#!/usr/bin/env python3\n")
        with zipfile.ZipFile(
            stream,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            entries = {
                path.relative_to(stage).as_posix(): path.read_bytes()
                for path in stage.rglob("*")
                if path.is_file()
            }
            entries["__main__.py"] = _MAIN
            for name, content in sorted(entries.items()):
                info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (0o100644 & 0xFFFF) << 16
                archive.writestr(info, content, compresslevel=9)


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
        # Ask zipapp to validate the staged package/main contract, then write the
        # release archive with normalized ordering, timestamps, and permissions.
        zipapp.create_archive(
            stage,
            target=stage.parent / "contract-check.pyz",
            main="codex_storage_doctor.cli:main",
            interpreter="/usr/bin/env python3",
            compressed=True,
        )
        normalized = stage.parent / "reproducible.pyz"
        _write_reproducible_archive(stage, normalized)
        staged_target = output.with_suffix(output.suffix + ".tmp")
        if staged_target.exists():
            raise FileExistsError(
                f"refusing to overwrite temporary artifact: {staged_target}"
            )
        shutil.copyfile(normalized, staged_target)
        staged_target.replace(output)
        if os.name != "nt":
            output.chmod(0o755)
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
