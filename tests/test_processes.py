from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_storage_doctor.mitigation import (
    SafetyGateError,
    ensure_process_gate,
)
from codex_storage_doctor.models import ProcessObservation, ProcessScan
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

            def runner(command, **kwargs):
                del kwargs
                self.assertEqual(command[0], "lsof")
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=f"p42\nccodex\nn{database}\n",
                    stderr="",
                )

            with patch("codex_storage_doctor.processes.os.readlink", fake_readlink):
                result = scan_codex_processes(
                    (),
                    platform_name="linux",
                    proc_root=root / "proc",
                    runner=runner,
                )
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.open_database_paths, (database.absolute(),))
            self.assertEqual(result.observations[0].write_bytes, 1234)
            rendered = json.dumps(result.to_dict())
            self.assertNotIn(str(database), rendered)
            self.assertNotIn("synthetic missing link", rendered)

    def test_linux_generic_holder_blocks_gate_without_claiming_codex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "logs_2.sqlite"
            database.write_bytes(b"synthetic")
            process = root / "proc" / "42"
            (process / "fd").mkdir(parents=True)
            (process / "comm").write_text("node\n", encoding="utf-8")

            def runner(command, **kwargs):
                del kwargs
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=f"p42\ncnode\nn{database}\n",
                    stderr="",
                )

            result = scan_codex_processes(
                (database,),
                platform_name="linux",
                proc_root=root / "proc",
                runner=runner,
            )
            self.assertEqual(result.status, "ok")
            self.assertFalse(result.codex_running)
            self.assertEqual(result.open_database_paths, ())
            self.assertEqual(
                result.held_database_paths,
                (database.absolute(),),
            )
            self.assertFalse(result.observations[0].is_codex)
            with self.assertRaisesRegex(SafetyGateError, "database is open"):
                ensure_process_gate(
                    database,
                    process_scanner=lambda **_kwargs: result,
                )

    def test_linux_target_holder_enumeration_failure_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "logs_2.sqlite"
            database.write_bytes(b"synthetic")
            (root / "proc").mkdir()

            def runner(command, **kwargs):
                del command, kwargs
                raise PermissionError("synthetic denied")

            result = scan_codex_processes(
                (database,),
                platform_name="linux",
                proc_root=root / "proc",
                runner=runner,
            )
            self.assertEqual(result.status, "partial")
            self.assertFalse(result.handle_evidence_supported)

    def test_linux_malformed_and_timed_out_lsof_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "logs_2.sqlite"
            database.write_bytes(b"synthetic")
            (root / "proc").mkdir()

            def malformed_runner(command, **kwargs):
                self.assertEqual(kwargs["timeout"], 3.0)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="not-lsof-machine-fields\n",
                    stderr="",
                )

            def timeout_runner(command, **kwargs):
                self.assertEqual(kwargs["timeout"], 3.0)
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])

            for runner in (malformed_runner, timeout_runner):
                with self.subTest(runner=runner.__name__):
                    result = scan_codex_processes(
                        (database,),
                        platform_name="linux",
                        proc_root=root / "proc",
                        runner=runner,
                    )
                    self.assertEqual(result.status, "partial")
                    self.assertFalse(result.handle_evidence_supported)

    def test_linux_proc_pid_stat_error_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "logs_2.sqlite"
            database.write_bytes(b"synthetic")
            process = root / "proc" / "42"
            process.mkdir(parents=True)
            real_stat = Path.stat
            denial_count = 0

            def fail_pid_stat(path, *args, **kwargs):
                nonlocal denial_count
                if (
                    denial_count == 0
                    and path.name == "42"
                    and path.parent.name == "proc"
                ):
                    denial_count += 1
                    raise PermissionError("synthetic stat denial")
                return real_stat(path, *args, **kwargs)

            def runner(command, **kwargs):
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout="",
                    stderr="",
                )

            with (
                patch.object(Path, "stat", fail_pid_stat),
                patch(
                    "codex_storage_doctor.processes.os.geteuid",
                    create=True,
                    return_value=0,
                ),
            ):
                result = scan_codex_processes(
                    (database,),
                    platform_name="linux",
                    proc_root=root / "proc",
                    runner=runner,
                )
            self.assertEqual(denial_count, 1)
            self.assertEqual(result.status, "partial")
            self.assertFalse(result.handle_evidence_supported)

    def test_linux_lsof_no_match_and_error_are_distinguished(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "logs_2.sqlite"
            database.write_bytes(b"synthetic")
            (root / "proc").mkdir()

            for stderr, expected_status in (
                ("", "ok"),
                ("permission denied", "partial"),
            ):
                with self.subTest(stderr=stderr):
                    def runner(command, **kwargs):
                        del kwargs
                        self.assertIn("-w", command)
                        return subprocess.CompletedProcess(
                            command,
                            1,
                            stdout="",
                            stderr=stderr,
                        )

                    result = scan_codex_processes(
                        (database,),
                        platform_name="linux",
                        proc_root=root / "proc",
                        runner=runner,
                    )
                    self.assertEqual(result.status, expected_status)
                    self.assertEqual(result.open_database_paths, ())
                    self.assertEqual(result.held_database_paths, ())

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
                    stdout=f"p77\nccodex\nn{database}\n",
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

    def test_macos_generic_holder_is_separate_from_codex_activity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "logs_2.sqlite"
            database.write_bytes(b"synthetic")

            def runner(command, **kwargs):
                del kwargs
                if command[0] == "ps":
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout="",
                        stderr="",
                    )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=f"p88\ncnode\nn{database}\n",
                    stderr="",
                )

            result = scan_codex_processes(
                (database,),
                platform_name="darwin",
                runner=runner,
            )
            self.assertEqual(result.status, "ok")
            self.assertFalse(result.codex_running)
            self.assertEqual(result.open_database_paths, ())
            self.assertEqual(
                result.held_database_paths,
                (database.absolute(),),
            )

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

    def test_gate_excludes_only_exact_known_self_holder(self) -> None:
        database = Path("/synthetic/logs_2.sqlite")
        own_holder = ProcessObservation(
            pid=os.getpid(),
            surface="database-holder",
            executable_basename="python",
            is_codex=False,
            open_database_ids=("database-001",),
        )
        own_scan = ProcessScan(
            status="ok",
            observations=(own_holder,),
            held_database_paths=(database,),
        )
        ensure_process_gate(
            database,
            process_scanner=lambda **_kwargs: own_scan,
            allowed_holder_pids=frozenset({os.getpid()}),
        )

        other_holder = ProcessObservation(
            pid=os.getpid() + 1,
            surface="database-holder",
            executable_basename="sqlite3",
            is_codex=False,
            open_database_ids=("database-001",),
        )
        blocked_scan = ProcessScan(
            status="ok",
            observations=(own_holder, other_holder),
            held_database_paths=(database,),
        )
        with self.assertRaisesRegex(SafetyGateError, "database is open"):
            ensure_process_gate(
                database,
                process_scanner=lambda **_kwargs: blocked_scan,
                allowed_holder_pids=frozenset({os.getpid()}),
            )


if __name__ == "__main__":
    unittest.main()
