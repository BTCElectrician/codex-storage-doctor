#!/usr/bin/env python3
"""Run the suite with disposable homes and no ambient executable lookup."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="codex-storage-doctor-tests-"
    ) as temporary:
        isolated = Path(temporary)
        home = isolated / "home"
        codex_home = isolated / "codex-home"
        sqlite_home = isolated / "sqlite-home"
        for path in (home, codex_home, sqlite_home):
            path.mkdir()
        environment = dict(os.environ)
        system_path = (
            str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
            if os.name == "nt"
            else "/usr/bin:/bin:/usr/sbin:/sbin"
        )
        environment.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "CODEX_HOME": str(codex_home),
                "CODEX_SQLITE_HOME": str(sqlite_home),
                "PATH": system_path,
                "PYTHONPATH": str(root / "src"),
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(root / "tests"),
                "-v",
            ],
            cwd=root,
            env=environment,
            check=False,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
