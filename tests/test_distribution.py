from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile

from scripts.build_wheel import build as build_wheel
from scripts.build_zipapp import build


class DistributionTests(unittest.TestCase):
    def test_zipapp_contains_current_source_without_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = build(Path(directory) / "doctor.pyz")
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                root_entrypoint = archive.read("__main__.py")
            self.assertIn("codex_storage_doctor/filesystem.py", names)
            self.assertIn("codex_storage_doctor/schema.py", names)
            self.assertIn(
                b"raise SystemExit(codex_storage_doctor.cli.main())",
                root_entrypoint,
            )
            self.assertFalse(
                any("__pycache__" in name or name.endswith(".pyc") for name in names)
            )

    def test_zipapp_build_is_byte_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = build(Path(directory) / "first.pyz").read_bytes()
            second = build(Path(directory) / "second.pyz").read_bytes()
        self.assertEqual(first, second)

    def test_zipapp_propagates_handled_cli_failure_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = build(root / "doctor.pyz")
            isolated_home = root / "home"
            isolated_home.mkdir()
            environment = {
                **os.environ,
                "HOME": str(isolated_home),
                "USERPROFILE": str(isolated_home),
                "CODEX_HOME": str(isolated_home / "codex-home"),
                "CODEX_SQLITE_HOME": str(isolated_home / "sqlite-home"),
                "PATH": "",
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    str(output),
                    "plan",
                    "--database",
                    str(root / "missing" / "logs_2.sqlite"),
                    "--mode",
                    "balanced",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Input error", completed.stderr)

    def test_wheel_build_is_byte_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = build_wheel(Path(directory) / "first").read_bytes()
            second = build_wheel(Path(directory) / "second").read_bytes()
        self.assertEqual(first, second)

    def test_private_operational_artifact_patterns_are_ignored(self) -> None:
        root = Path(__file__).resolve().parents[1]
        patterns = set((root / ".gitignore").read_text(encoding="utf-8").splitlines())
        expected_patterns = {
            ".codex-storage-doctor/",
            "doctor-plan*.json",
            "plan.json",
            "apply-result.json",
            "verify-result.json",
            "audit-result.json",
            "rollback-manifest*.json",
            "rollback-result*.json",
            "codex-storage-report*.json",
        }
        self.assertTrue(expected_patterns.issubset(patterns))

        representative_paths = (
            ".codex-storage-doctor/rollback/private/manifest.json",
            "doctor-plan-private.json",
            "plan.json",
            "apply-result.json",
            "verify-result.json",
            "audit-result.json",
            "rollback-manifest-private.json",
            "rollback-result-private.json",
            "codex-storage-report-private.json",
        )
        git_executable = shutil.which("git") or shutil.which("git.exe")
        if git_executable is None and os.name == "nt":
            windows_candidates = (
                Path(os.environ.get(variable, "")) / "Git" / "cmd" / "git.exe"
                for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")
                if os.environ.get(variable)
            )
            git_executable = next(
                (
                    str(candidate)
                    for candidate in windows_candidates
                    if candidate.is_file()
                ),
                None,
            )
        self.assertIsNotNone(
            git_executable,
            "Git is required to verify ignore behavior",
        )
        completed = subprocess.run(
            [
                str(git_executable),
                "check-ignore",
                "--no-index",
                "-z",
                "--stdin",
            ],
            cwd=root,
            input=(
                b"\0".join(os.fsencode(path) for path in representative_paths)
                + b"\0"
            ),
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            os.fsdecode(completed.stderr),
        )
        self.assertEqual(
            {
                os.fsdecode(path)
                for path in completed.stdout.split(b"\0")
                if path
            },
            set(representative_paths),
        )

    def test_build_inputs_are_pinned(self) -> None:
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            project["build-system"]["requires"],
            ["setuptools==83.0.0"],
        )
        workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn(
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
            workflow,
        )
        self.assertIn(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            workflow,
        )
        self.assertIn('"setuptools==83.0.0"', workflow)
        self.assertIn('"wheel==0.47.0"', workflow)

    def test_current_public_safety_claims_are_bounded(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        security = (root / "SECURITY.md").read_text(encoding="utf-8")
        status = (root / "STATUS.md").read_text(encoding="utf-8")
        self.assertNotIn("public source pre-release", readme)
        self.assertNotIn("98 passing synthetic regressions", readme)
        self.assertIn("v0.1.1", readme)
        self.assertIn("v0.1.1", security)
        self.assertIn("v0.1.1", status)
        active_paths = (
            root / "README.md",
            root / "SECURITY.md",
            root / "STATUS.md",
            root / "docs" / "EVIDENCE.md",
            root / "docs" / "PLAN.md",
            root / "docs" / "SAFETY.md",
            root
            / "plugins"
            / "codex-storage-doctor"
            / "skills"
            / "codex-storage-doctor"
            / "SKILL.md",
            root / "src" / "codex_storage_doctor" / "cli.py",
        )
        current_claims = "\n".join(
            path.read_text(encoding="utf-8") for path in active_paths
        )
        self.assertNotIn("No known diagnostic insert/prune churn", current_claims)
        self.assertNotIn("unpublished local pre-release", current_claims)
        self.assertNotIn("immutable plan and rollback artifacts", current_claims)
        self.assertIn("PATH CLI version is advisory", current_claims)
        self.assertIn("stat-bounded", current_claims)
        self.assertIn("coarse modification-time resolution", current_claims)
        self.assertIn("pruning statement after an ignored insert", current_claims)
        self.assertNotIn(
            "mutation_occurred_recovery_required",
            current_claims,
        )


if __name__ == "__main__":
    unittest.main()
