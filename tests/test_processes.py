from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_storage_doctor.processes import scan_codex_processes


class ProcessAdapterTests(unittest.TestCase):
    def test_linux_proc_adapter_matches_handle_without_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "logs_2.sqlite"
            database.write_bytes(b"synthetic")
            process = root / "proc" / "42"
            (process / "fd").mkdir(parents=True)
            (process / "comm").write_text("codex\n", encoding="utf-8")
            (process / "io").write_text("write_bytes: 1234\n", encoding="utf-8")
            exe = process / "exe"
            descriptor = process / "fd" / "7"
            descriptor.touch()

            def fake_readlink(path: os.PathLike[str] | str) -> str:
                value = Path(path)
                if value == exe:
                    return "/usr/local/bin/codex"
                if value == descriptor:
                    return str(database)
                raise OSError("synthetic missing link")

            with patch("codex_storage_doctor.processes.os.readlink", fake_readlink):
                result = scan_codex_processes(
                    (),
                    platform_name="linux",
                    proc_root=root / "proc",
                )
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.open_database_paths, (database.absolute(),))
            self.assertEqual(result.observations[0].write_bytes, 1234)
            rendered = json.dumps(result.to_dict())
            self.assertNotIn(str(database), rendered)
            self.assertNotIn("synthetic missing link", rendered)

    def test_macos_adapter_parses_ps_and_lsof_but_not_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "logs_2.sqlite"
            database.write_bytes(b"synthetic")

            def runner(command, **kwargs):
                del kwargs
                if command[0] == "ps":
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=" 77 /Applications/Codex.app/Contents/MacOS/Codex\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=f"p77\nn{database}\n",
                    stderr="",
                )

            result = scan_codex_processes(
                (),
                platform_name="darwin",
                runner=runner,
            )
            self.assertEqual(result.status, "ok")
            self.assertTrue(result.codex_running)
            self.assertEqual(result.open_database_paths, (database.absolute(),))
            rendered = json.dumps(result.to_dict())
            self.assertNotIn(str(database), rendered)
            self.assertNotIn("Contents/MacOS", rendered)

    def test_windows_is_explicitly_partial_without_handle_tooling(self) -> None:
        def runner(command, **kwargs):
            del kwargs
            payload = [
                {
                    "Id": 91,
                    "ProcessName": "codex",
                    "Path": r"C:\Tools\codex.exe",
                }
            ]
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(payload),
                stderr="",
            )

        result = scan_codex_processes(
            (),
            platform_name="win32",
            runner=runner,
        )
        self.assertEqual(result.status, "partial")
        self.assertFalse(result.handle_evidence_supported)
        self.assertTrue(result.codex_running)
        self.assertEqual(
            result.findings[0].code,
            "windows_handle_evidence_unsupported",
        )

    def test_unknown_platform_is_partial_not_a_guess(self) -> None:
        result = scan_codex_processes((), platform_name="plan9")
        self.assertEqual(result.status, "unsupported")
        self.assertFalse(result.handle_evidence_supported)


if __name__ == "__main__":
    unittest.main()
