from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from helpers import clear_process_scan, create_database
from codex_storage_doctor import cli, mitigation
from codex_storage_doctor.mitigation import (
    MutationRecoveryRequired,
    SafetyGateError,
    _post_commit_recovery_result,
    _rollback_reconciliation_result,
    apply_plan,
    ensure_process_gate,
)
from codex_storage_doctor.models import ProcessObservation, ProcessScan
from codex_storage_doctor.planning import create_plan
from codex_storage_doctor.privacy import PrivacyViolation, assert_privacy_safe
from codex_storage_doctor.processes import scan_codex_processes
from codex_storage_doctor.sampling import sample_database


class FreshReviewRegressionTests(unittest.TestCase):
    def test_prepared_manifest_verify_is_indeterminate_and_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            with patch(
                "codex_storage_doctor.planning.observed_codex_version",
                return_value=None,
            ):
                plan = create_plan(database, "balanced")
            real_write = mitigation.write_private_json

            def leave_prepared_manifest(path, value, *, overwrite=False):
                if overwrite:
                    raise OSError("synthetic finalization failure")
                return real_write(path, value, overwrite=overwrite)

            with (
                patch(
                    "codex_storage_doctor.mitigation.write_private_json",
                    side_effect=leave_prepared_manifest,
                ),
                patch(
                    "codex_storage_doctor.mitigation.observed_codex_version",
                    return_value=None,
                ),
                self.assertRaises(MutationRecoveryRequired) as caught,
            ):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )

            manifest_path = Path(caught.exception.result["manifest"])

            def sampled(path, seconds):
                return sample_database(
                    path,
                    seconds,
                    process_scan=ProcessScan(status="ok"),
                    sleep_fn=lambda _seconds: None,
                )

            stdout = io.StringIO()
            with (
                patch.object(cli, "sample_database", side_effect=sampled),
                patch.object(cli, "observed_codex_version", return_value=None),
                patch("sys.stdout", stdout),
            ):
                code = cli.main(
                    [
                        "verify",
                        "--database",
                        str(database),
                        "--manifest",
                        str(manifest_path),
                        "--sample-seconds",
                        "0",
                        "--json",
                    ]
                )

            self.assertEqual(code, cli.EXIT_PARTIAL)
            context = json.loads(stdout.getvalue())["manifest_context"]
            self.assertEqual(
                context["expected_state"],
                "indeterminate_prepared",
            )
            self.assertFalse(context["mode_matches"])
            self.assertFalse(context["matches"])

    def test_specific_malformed_lsof_record_shapes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "logs_2.sqlite"
            database.write_bytes(b"synthetic")
            proc_root = root / "proc"
            proc_root.mkdir()
            malformed_outputs = (
                f"pnot-a-pid\ncnode\nn{database}\n",
                f"n{database}\n",
                "p42\ncnode\n",
                f"p{os.getpid()}\nn{database}\n",
                "p42\ncnode\nn/not/the/selected/database.sqlite\n",
                (
                    f"p{os.getpid()}\ncpython\nn{database}\n"
                    "p987654\ncsqlite3\n"
                ),
            )
            for output in malformed_outputs:
                with self.subTest(output=output):
                    def runner(command, **kwargs):
                        self.assertEqual(kwargs["timeout"], 3.0)
                        return subprocess.CompletedProcess(
                            command,
                            0,
                            stdout=output,
                            stderr="",
                        )

                    scan = scan_codex_processes(
                        (database,),
                        platform_name="linux",
                        proc_root=proc_root,
                        runner=runner,
                    )
                    self.assertEqual(scan.status, "partial")
                    self.assertFalse(scan.handle_evidence_supported)
                    with self.assertRaises(SafetyGateError):
                        ensure_process_gate(
                            database,
                            process_scanner=lambda **_kwargs: scan,
                        )

    def test_colon_adjacent_posix_path_fails_privacy_boundary(self) -> None:
        private_paths = (
            "codex-version:/Users/synthetic/private",
            "codex-version://server/share/private",
            "prefix://server/share/private",
        )
        for private_path in private_paths:
            with (
                self.subTest(private_path=private_path),
                self.assertRaises(PrivacyViolation),
            ):
                assert_privacy_safe(
                    {"detail": private_path},
                    forbid_absolute_paths=True,
                )
        assert_privacy_safe(
            {"detail": "source:https://github.com/openai/codex"},
            forbid_absolute_paths=True,
        )

    def test_self_holder_exclusion_rejects_near_matches(self) -> None:
        database = Path("/synthetic/logs_2.sqlite")
        near_matches = (
            ProcessObservation(
                pid=os.getpid(),
                surface="codex",
                executable_basename="codex",
                is_codex=True,
                open_database_ids=("database-001",),
            ),
            ProcessObservation(
                pid=os.getpid(),
                surface="database-holder",
                executable_basename="python",
                is_codex=False,
                open_database_ids=("database-002",),
            ),
            ProcessObservation(
                pid=os.getpid() + 1,
                surface="database-holder",
                executable_basename="python",
                is_codex=False,
                open_database_ids=("database-001",),
            ),
        )
        for observation in near_matches:
            with self.subTest(observation=observation):
                scan = ProcessScan(
                    status="ok",
                    observations=(observation,),
                    held_database_paths=(database,),
                )
                with self.assertRaises(SafetyGateError):
                    ensure_process_gate(
                        database,
                        process_scanner=lambda **_kwargs: scan,
                        allowed_holder_pids=frozenset({os.getpid()}),
                    )

    def test_unverified_recovery_surfaces_every_token_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "rollback-manifest.json"
            manifest_path.write_text("{invalid", encoding="utf-8")
            common = {
                "database": root / "logs_2.sqlite",
                "trigger_name": "codex_storage_doctor_v1_balanced",
                "manifest_path": manifest_path,
                "backup_path": root / "backup.sqlite",
                "backup_hash": "a" * 64,
                "error": OSError("synthetic"),
            }
            apply_result = _post_commit_recovery_result(
                **common,
                prepared_token="ROLLBACK-PREPARED",
                current_token="ROLLBACK-ADVANCED",
            )
            rollback_result = _rollback_reconciliation_result(
                **common,
                original_token="ROLLBACK-ORIGINAL",
                current_token="ROLLBACK-ROLLED-BACK",
            )

        self.assertEqual(
            apply_result["rollback_token_candidates"],
            ["ROLLBACK-PREPARED", "ROLLBACK-ADVANCED"],
        )
        self.assertEqual(
            rollback_result["rollback_token_candidates"],
            ["ROLLBACK-ORIGINAL", "ROLLBACK-ROLLED-BACK"],
        )
        apply_text = cli._apply_text(apply_result)
        rollback_text = cli._rollback_text(rollback_result)
        for token in apply_result["rollback_token_candidates"]:
            self.assertIn(token, apply_text)
        for token in rollback_result["rollback_token_candidates"]:
            self.assertIn(token, rollback_text)


if __name__ == "__main__":
    unittest.main()
