from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from helpers import clear_process_scan, create_database
from codex_storage_doctor import cli
from codex_storage_doctor import mitigation
from codex_storage_doctor.models import ProcessObservation, ProcessScan
from codex_storage_doctor.planning import TRIGGER_SQL, create_plan
from codex_storage_doctor.reports import read_json_object, write_private_json
from codex_storage_doctor.sampling import sample_database


class CLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.planning_version_patch = patch(
            "codex_storage_doctor.planning.observed_codex_version",
            return_value=None,
        )
        self.mitigation_version_patch = patch(
            "codex_storage_doctor.mitigation.observed_codex_version",
            return_value=None,
        )
        self.cli_version_patch = patch.object(
            cli,
            "observed_codex_version",
            return_value=None,
        )
        self.process_patch = patch.object(
            cli,
            "scan_codex_processes",
            return_value=ProcessScan(status="ok"),
        )
        for patcher in (
            self.planning_version_patch,
            self.mitigation_version_patch,
            self.cli_version_patch,
            self.process_patch,
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _seed_private_row(self, database: Path) -> None:
        connection = sqlite3.connect(database)
        connection.execute(
            """
            INSERT INTO logs (
                ts, ts_nanos, level, target, feedback_log_body,
                module_path, file, line, thread_id, process_uuid,
                estimated_bytes
            ) VALUES (1, 0, 'TRACE', 'PRIVATE-TARGET',
                      'PRIVATE-BODY-CANARY', 'PRIVATE-MODULE',
                      'PRIVATE-FILE', 1, 'PRIVATE-THREAD',
                      'PRIVATE-PROCESS', 123)
            """
        )
        connection.commit()
        connection.close()

    def test_audit_json_omits_paths_and_private_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            self._seed_private_row(database)
            stdout = io.StringIO()
            isolated_home = Path(directory) / "isolated-home"
            isolated_home.mkdir()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("pathlib.Path.home", return_value=isolated_home),
                patch.object(
                    cli,
                    "scan_codex_processes",
                    return_value=ProcessScan(status="ok"),
                ),
                patch("sys.stdout", stdout),
            ):
                code = cli.main(
                    ["audit", "--sqlite-home", str(database), "--json"]
                )
            self.assertEqual(code, cli.EXIT_OK)
            output = stdout.getvalue()
            report = json.loads(output)
            self.assertEqual(report["databases"][0]["inspection"]["row_count"], 1)
            self.assertNotIn(str(database), output)
            for canary in (
                "PRIVATE-TARGET",
                "PRIVATE-BODY-CANARY",
                "PRIVATE-MODULE",
                "PRIVATE-FILE",
                "PRIVATE-THREAD",
                "PRIVATE-PROCESS",
            ):
                self.assertNotIn(canary, output)

    def test_support_json_sanitizes_profile_and_schema_path_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sqlite_home = root / "sqlite-home"
            sqlite_home.mkdir()
            database = create_database(sqlite_home)
            schema_canary = "client_/Users/synthetic/schema-private"
            type_canary = "TYPE_/Users/synthetic/type-private"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    f'ALTER TABLE logs ADD COLUMN "{schema_canary}" '
                    f'"{type_canary}"'
                )
                connection.commit()
            finally:
                connection.close()

            profile_canary = "/Users/synthetic/profile-private"
            codex_home = root / "codex-home"
            codex_home.mkdir()
            codex_home.joinpath("config.toml").write_text(
                "\n".join(
                    (
                        f'profile = "{profile_canary}"',
                        f'[profiles."{profile_canary}"]',
                        f"sqlite_home = {json.dumps(str(sqlite_home))}",
                    )
                ),
                encoding="utf-8",
            )
            isolated_home = root / "isolated-home"
            isolated_home.mkdir()
            stdout = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("pathlib.Path.home", return_value=isolated_home),
                patch.object(
                    cli,
                    "scan_codex_processes",
                    return_value=ProcessScan(status="ok"),
                ),
                patch("sys.stdout", stdout),
            ):
                code = cli.main(
                    [
                        "audit",
                        "--codex-home",
                        str(codex_home),
                        "--for-support",
                        "--json",
                    ]
                )

            self.assertEqual(code, cli.EXIT_OK)
            rendered = stdout.getvalue()
            self.assertNotIn(profile_canary, rendered)
            self.assertNotIn(schema_canary, rendered)
            self.assertNotIn(type_canary, rendered)
            report = json.loads(rendered)
            inspection = report["databases"][0]["inspection"]
            self.assertEqual(
                inspection["unrecognized_schema_column_count"],
                1,
            )

    def test_no_database_returns_stable_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("pathlib.Path.home", return_value=Path(directory)),
                patch.object(
                    cli,
                    "scan_codex_processes",
                    return_value=ProcessScan(status="ok"),
                ),
                patch("sys.stderr", stderr),
            ):
                code = cli.main(["audit"])
            self.assertEqual(code, cli.EXIT_NOT_FOUND)
            self.assertIn("No Codex diagnostic", stderr.getvalue())

    def test_open_handle_can_discover_unconfigured_log_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            empty_home = root / "empty-home"
            empty_home.mkdir()
            scan = ProcessScan(
                status="ok",
                observations=(
                    ProcessObservation(
                        pid=7,
                        surface="codex",
                        executable_basename="codex",
                        open_database_ids=("database-001",),
                    ),
                ),
                open_database_paths=(database,),
            )
            stdout = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("pathlib.Path.home", return_value=empty_home),
                patch.object(cli, "scan_codex_processes", return_value=scan),
                patch("sys.stdout", stdout),
            ):
                code = cli.main(["audit", "--json"])
            self.assertEqual(code, cli.EXIT_OK)
            report = json.loads(stdout.getvalue())
            candidate = report["databases"][0]["candidate"]
            self.assertEqual(candidate["sources"], ["process:open_handle"])
            self.assertIn("open_by_codex_process", candidate["evidence_labels"])

    def test_plan_apply_and_rollback_command_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan_path = root / "plan.json"
            with (
                patch(
                    "codex_storage_doctor.planning.observed_codex_version",
                    return_value=None,
                ),
                patch("sys.stdout", io.StringIO()),
            ):
                code = cli.main(
                    [
                        "plan",
                        "--database",
                        str(database),
                        "--mode",
                        "balanced",
                        "--output",
                        str(plan_path),
                    ]
                )
            self.assertEqual(code, cli.EXIT_OK)
            self.assertEqual(database.name, "logs_2.sqlite")
            plan = read_json_object(plan_path)

            with (
                patch(
                    "codex_storage_doctor.processes.scan_codex_processes",
                    side_effect=clear_process_scan,
                ),
                patch("sys.stdout", io.StringIO()),
            ):
                code = cli.main(
                    [
                        "apply",
                        "--plan",
                        str(plan_path),
                        "--confirm",
                        plan["confirmation_token"],
                    ]
                )
            self.assertEqual(code, cli.EXIT_OK)
            manifests = list(
                (root / ".codex-storage-doctor" / "rollback").glob(
                    "*/rollback-manifest.json"
                )
            )
            self.assertEqual(len(manifests), 1)
            manifest = read_json_object(manifests[0])

            with (
                patch(
                    "codex_storage_doctor.processes.scan_codex_processes",
                    side_effect=clear_process_scan,
                ),
                patch("sys.stdout", io.StringIO()),
            ):
                code = cli.main(
                    [
                        "rollback",
                        "--manifest",
                        str(manifests[0]),
                        "--confirm",
                        manifest["rollback_token"],
                    ]
                )
            self.assertEqual(code, cli.EXIT_OK)

    def test_apply_post_commit_failure_has_distinct_recovery_exit_and_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "balanced")
            plan_path = root / "plan.json"
            write_private_json(plan_path, plan)
            real_write = mitigation.write_private_json

            def fail_final_manifest(path, value, *, overwrite=False):
                if overwrite:
                    raise OSError("synthetic finalization failure")
                return real_write(path, value, overwrite=overwrite)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch(
                    "codex_storage_doctor.processes.scan_codex_processes",
                    side_effect=clear_process_scan,
                ),
                patch(
                    "codex_storage_doctor.mitigation.write_private_json",
                    side_effect=fail_final_manifest,
                ),
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                code = cli.main(
                    [
                        "apply",
                        "--plan",
                        str(plan_path),
                        "--confirm",
                        plan["confirmation_token"],
                        "--json",
                    ]
                )

            self.assertEqual(code, cli.EXIT_RECOVERY_REQUIRED)
            recovery = json.loads(stdout.getvalue())
            self.assertEqual(
                recovery["status"],
                "mutation_recovery_required",
            )
            self.assertIn(
                "MUTATION OCCURRED; RECOVERY REQUIRED",
                stderr.getvalue(),
            )
            manifest = read_json_object(Path(recovery["manifest"]))
            self.assertEqual(
                recovery["rollback_token"],
                manifest["rollback_token"],
            )

    def test_recovery_coordinates_survive_optional_output_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "maximum")
            plan_path = root / "plan.json"
            write_private_json(plan_path, plan)
            refused_output = root / "existing-output.json"
            refused_output.write_text("do not overwrite", encoding="utf-8")
            real_write = mitigation.write_private_json

            def fail_final_manifest(path, value, *, overwrite=False):
                if overwrite:
                    raise OSError("synthetic finalization failure")
                return real_write(path, value, overwrite=overwrite)

            stderr = io.StringIO()
            with (
                patch(
                    "codex_storage_doctor.processes.scan_codex_processes",
                    side_effect=clear_process_scan,
                ),
                patch(
                    "codex_storage_doctor.mitigation.write_private_json",
                    side_effect=fail_final_manifest,
                ),
                patch("sys.stderr", stderr),
            ):
                code = cli.main(
                    [
                        "apply",
                        "--plan",
                        str(plan_path),
                        "--confirm",
                        plan["confirmation_token"],
                        "--output",
                        str(refused_output),
                    ]
                )

            self.assertEqual(code, cli.EXIT_RECOVERY_REQUIRED)
            rendered = stderr.getvalue()
            self.assertIn(
                "MUTATION OCCURRED; RECOVERY REQUIRED",
                rendered,
            )
            manifests = list(
                (root / ".codex-storage-doctor" / "rollback").glob(
                    "*/rollback-manifest.json"
                )
            )
            self.assertEqual(len(manifests), 1)
            manifest = read_json_object(manifests[0])
            reported_manifest = (
                Path(str(manifest["backup_path"])).parent
                / "rollback-manifest.json"
            )
            self.assertTrue(reported_manifest.samefile(manifests[0]))
            self.assertIn(str(reported_manifest), rendered)
            self.assertIn(manifest["rollback_token"], rendered)
            self.assertEqual(
                refused_output.read_text(encoding="utf-8"),
                "do not overwrite",
            )

    def test_successful_apply_then_result_output_failure_exits_recovery(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "balanced")
            plan_path = root / "plan.json"
            write_private_json(plan_path, plan)
            refused_output = root / "existing-apply-result.json"
            refused_output.write_text("preserve", encoding="utf-8")
            stderr = io.StringIO()

            with (
                patch(
                    "codex_storage_doctor.processes.scan_codex_processes",
                    side_effect=clear_process_scan,
                ),
                patch("sys.stderr", stderr),
            ):
                code = cli.main(
                    [
                        "apply",
                        "--plan",
                        str(plan_path),
                        "--confirm",
                        plan["confirmation_token"],
                        "--output",
                        str(refused_output),
                    ]
                )

            self.assertEqual(code, cli.EXIT_RECOVERY_REQUIRED)
            rendered = stderr.getvalue()
            self.assertIn("MUTATION OCCURRED; RECOVERY REQUIRED", rendered)
            manifests = list(
                (root / ".codex-storage-doctor" / "rollback").glob(
                    "*/rollback-manifest.json"
                )
            )
            self.assertEqual(len(manifests), 1)
            manifest = read_json_object(manifests[0])
            self.assertEqual(manifest["status"], "applied")
            reported_manifest = (
                Path(str(manifest["backup_path"])).parent
                / "rollback-manifest.json"
            )
            self.assertTrue(reported_manifest.samefile(manifests[0]))
            self.assertIn(str(reported_manifest), rendered)
            self.assertIn(manifest["rollback_token"], rendered)
            self.assertEqual(refused_output.read_text(), "preserve")

    def test_successful_apply_then_runtime_emit_failure_exits_recovery(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "balanced")
            plan_path = root / "plan.json"
            write_private_json(plan_path, plan)
            stderr = io.StringIO()

            with (
                patch(
                    "codex_storage_doctor.processes.scan_codex_processes",
                    side_effect=clear_process_scan,
                ),
                patch.object(
                    cli,
                    "_emit",
                    side_effect=RuntimeError("synthetic renderer failure"),
                ),
                patch("sys.stderr", stderr),
            ):
                code = cli.main(
                    [
                        "apply",
                        "--plan",
                        str(plan_path),
                        "--confirm",
                        plan["confirmation_token"],
                    ]
                )

            self.assertEqual(code, cli.EXIT_RECOVERY_REQUIRED)
            rendered = stderr.getvalue()
            self.assertIn("MUTATION OCCURRED; RECOVERY REQUIRED", rendered)
            manifests = list(
                (root / ".codex-storage-doctor" / "rollback").glob(
                    "*/rollback-manifest.json"
                )
            )
            self.assertEqual(len(manifests), 1)
            manifest = read_json_object(manifests[0])
            reported_manifest = (
                Path(str(manifest["backup_path"])).parent
                / "rollback-manifest.json"
            )
            self.assertTrue(reported_manifest.samefile(manifests[0]))
            self.assertIn(str(reported_manifest), rendered)
            self.assertIn(manifest["rollback_token"], rendered)

    def test_rollback_reconciliation_survives_optional_output_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "balanced")
            applied = cli.apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(applied["manifest"])
            manifest = read_json_object(manifest_path)
            refused_output = root / "existing-rollback-output.json"
            refused_output.write_text("do not overwrite", encoding="utf-8")
            real_write = mitigation.write_private_json

            def fail_manifest_advance(path, value, *, overwrite=False):
                if overwrite:
                    raise OSError("synthetic rollback finalization failure")
                return real_write(path, value, overwrite=overwrite)

            stderr = io.StringIO()
            with (
                patch(
                    "codex_storage_doctor.processes.scan_codex_processes",
                    side_effect=clear_process_scan,
                ),
                patch(
                    "codex_storage_doctor.mitigation.write_private_json",
                    side_effect=fail_manifest_advance,
                ),
                patch("sys.stderr", stderr),
            ):
                code = cli.main(
                    [
                        "rollback",
                        "--manifest",
                        str(manifest_path),
                        "--confirm",
                        manifest["rollback_token"],
                        "--output",
                        str(refused_output),
                    ]
                )

            self.assertEqual(code, cli.EXIT_RECOVERY_REQUIRED)
            rendered = stderr.getvalue()
            self.assertIn(
                "ROLLBACK OCCURRED; RECONCILIATION REQUIRED",
                rendered,
            )
            self.assertIn(str(manifest_path), rendered)
            self.assertIn(manifest["rollback_token"], rendered)
            self.assertEqual(
                refused_output.read_text(encoding="utf-8"),
                "do not overwrite",
            )

    def test_successful_rollback_then_result_output_failure_reconciles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "maximum")
            applied = cli.apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(applied["manifest"])
            manifest = read_json_object(manifest_path)
            refused_output = root / "existing-rollback-result.json"
            refused_output.write_text("preserve", encoding="utf-8")
            stderr = io.StringIO()

            with (
                patch(
                    "codex_storage_doctor.processes.scan_codex_processes",
                    side_effect=clear_process_scan,
                ),
                patch("sys.stderr", stderr),
            ):
                code = cli.main(
                    [
                        "rollback",
                        "--manifest",
                        str(manifest_path),
                        "--confirm",
                        manifest["rollback_token"],
                        "--output",
                        str(refused_output),
                    ]
                )

            self.assertEqual(code, cli.EXIT_RECOVERY_REQUIRED)
            rendered = stderr.getvalue()
            self.assertIn(
                "ROLLBACK OCCURRED; RECONCILIATION REQUIRED",
                rendered,
            )
            updated = read_json_object(manifest_path)
            self.assertEqual(updated["status"], "rolled_back")
            self.assertIn(str(manifest_path), rendered)
            self.assertIn(updated["rollback_token"], rendered)
            self.assertEqual(refused_output.read_text(), "preserve")
            connection = sqlite3.connect(database)
            try:
                trigger_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(trigger_count, 0)

    def test_successful_rollback_then_runtime_emit_failure_reconciles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "maximum")
            applied = cli.apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(applied["manifest"])
            manifest = read_json_object(manifest_path)
            stderr = io.StringIO()

            with (
                patch(
                    "codex_storage_doctor.processes.scan_codex_processes",
                    side_effect=clear_process_scan,
                ),
                patch.object(
                    cli,
                    "_emit",
                    side_effect=RuntimeError("synthetic renderer failure"),
                ),
                patch("sys.stderr", stderr),
            ):
                code = cli.main(
                    [
                        "rollback",
                        "--manifest",
                        str(manifest_path),
                        "--confirm",
                        manifest["rollback_token"],
                    ]
                )

            self.assertEqual(code, cli.EXIT_RECOVERY_REQUIRED)
            rendered = stderr.getvalue()
            self.assertIn(
                "ROLLBACK OCCURRED; RECONCILIATION REQUIRED",
                rendered,
            )
            updated = read_json_object(manifest_path)
            self.assertEqual(updated["status"], "rolled_back")
            self.assertIn(str(manifest_path), rendered)
            self.assertIn(updated["rollback_token"], rendered)

    def test_post_mutation_emit_does_not_swallow_base_exceptions(self) -> None:
        apply_result = {
            "changed": True,
            "database": "/synthetic/logs_2.sqlite",
            "trigger_name": "codex_storage_doctor_v1_balanced",
            "manifest": "/synthetic/rollback-manifest.json",
            "backup": "/synthetic/backup.sqlite",
            "backup_sha256": "a" * 64,
            "rollback_token": "ROLLBACK-SYNTHETIC",
        }
        apply_args = cli.build_parser().parse_args(
            [
                "apply",
                "--plan",
                "/synthetic/plan.json",
                "--confirm",
                "APPLY-SYNTHETIC",
            ]
        )
        rollback_result = {
            "changed": True,
            "database": "/synthetic/logs_2.sqlite",
            "trigger_name": "codex_storage_doctor_v1_balanced",
            "manifest": "/synthetic/rollback-manifest.json",
            "backup_path": "/synthetic/backup.sqlite",
            "backup_sha256": "a" * 64,
            "rollback_token": "ROLLBACK-SYNTHETIC",
            "record": "/synthetic/rollback-result.json",
        }
        rollback_args = cli.build_parser().parse_args(
            [
                "rollback",
                "--manifest",
                "/synthetic/rollback-manifest.json",
                "--confirm",
                "ROLLBACK-SYNTHETIC",
            ]
        )
        operations = (
            (
                "apply",
                cli._run_apply,
                apply_args,
                "apply_plan",
                apply_result,
                "MUTATION OCCURRED; RECOVERY REQUIRED",
            ),
            (
                "rollback",
                cli._run_rollback,
                rollback_args,
                "rollback",
                rollback_result,
                "ROLLBACK OCCURRED; RECONCILIATION REQUIRED",
            ),
        )
        interruptions = (
            ("KeyboardInterrupt", KeyboardInterrupt()),
            ("SystemExit", SystemExit(17)),
        )
        for (
            operation,
            runner,
            args,
            mutation_name,
            result,
            heading,
        ) in operations:
            for interruption_name, interruption in interruptions:
                stderr = io.StringIO()
                with (
                    self.subTest(
                        operation=operation,
                        interruption=interruption_name,
                    ),
                    patch.object(cli, "read_json_object", return_value={}),
                    patch.object(cli, mutation_name, return_value=result),
                    patch.object(cli, "_emit", side_effect=interruption),
                    patch("sys.stderr", stderr),
                    self.assertRaises(type(interruption)),
                ):
                    runner(args)
                rendered = stderr.getvalue()
                self.assertIn(heading, rendered)
                self.assertIn(result["manifest"], rendered)
                self.assertIn(result["rollback_token"], rendered)

    def test_default_recovery_text_surfaces_every_token_candidate(self) -> None:
        common = {
            "trigger_name": "codex_storage_doctor_balanced",
            "manifest": "/synthetic/rollback-manifest.json",
            "backup": "/synthetic/backup.sqlite",
            "backup_path": "/synthetic/backup.sqlite",
            "rollback_token": "ROLLBACK-FIRST",
            "rollback_token_candidates": [
                "ROLLBACK-FIRST",
                "ROLLBACK-SECOND",
            ],
        }
        apply_text = cli._apply_text({**common, "recovery_required": True})
        rollback_text = cli._rollback_text(
            {**common, "reconciliation_required": True}
        )
        for rendered in (apply_text, rollback_text):
            self.assertIn("ROLLBACK-FIRST", rendered)
            self.assertIn("ROLLBACK-SECOND", rendered)

    def test_plan_output_is_private_where_supported(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX mode bits are not portable to Windows")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan_path = root / "plan.json"
            with (
                patch(
                    "codex_storage_doctor.planning.observed_codex_version",
                    return_value=None,
                ),
                patch("sys.stdout", io.StringIO()),
            ):
                self.assertEqual(
                    cli.main(
                        [
                            "plan",
                            "--database",
                            str(database),
                            "--mode",
                            "maximum",
                            "--output",
                            str(plan_path),
                        ]
                    ),
                    cli.EXIT_OK,
                )
            self.assertEqual(plan_path.stat().st_mode & 0o777, 0o600)

    def test_invalid_sample_duration_is_usage_error(self) -> None:
        stderr = io.StringIO()
        with (
            patch("sys.stderr", stderr),
            self.assertRaises(SystemExit) as caught,
        ):
            cli.main(["audit", "--sample-seconds", "-1"])
        self.assertEqual(caught.exception.code, cli.EXIT_USAGE)
        self.assertIn("between 0 and 86400", stderr.getvalue())

    def test_malformed_json_artifacts_use_artifact_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            malformed = root / "malformed.json"
            malformed.write_text("{not-json", encoding="utf-8")
            commands = (
                [
                    "apply",
                    "--plan",
                    str(malformed),
                    "--confirm",
                    "synthetic",
                ],
                [
                    "verify",
                    "--database",
                    str(database),
                    "--manifest",
                    str(malformed),
                    "--sample-seconds",
                    "0",
                ],
                [
                    "rollback",
                    "--manifest",
                    str(malformed),
                    "--confirm",
                    "synthetic",
                ],
            )
            for command in commands:
                with self.subTest(command=command[0]):
                    stderr = io.StringIO()
                    with patch("sys.stderr", stderr):
                        code = cli.main(command)
                    self.assertEqual(code, cli.EXIT_ARTIFACT)
                    self.assertIn("Artifact operation failed", stderr.getvalue())

    def test_audit_passes_full_scan_to_bounded_sampling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            isolated_home = root / "isolated-home"
            isolated_home.mkdir()
            seen: list[bool] = []

            def sampled(path, seconds, *, full_scan=False):
                seen.append(full_scan)
                return sample_database(
                    path,
                    seconds,
                    process_scan=ProcessScan(status="ok"),
                    full_scan=full_scan,
                    sleep_fn=lambda _seconds: None,
                )

            with (
                patch.dict(os.environ, {}, clear=True),
                patch("pathlib.Path.home", return_value=isolated_home),
                patch.object(
                    cli,
                    "scan_codex_processes",
                    return_value=ProcessScan(status="ok"),
                ),
                patch.object(cli, "sample_database", side_effect=sampled),
                patch("sys.stdout", io.StringIO()),
            ):
                code = cli.main(
                    [
                        "audit",
                        "--sqlite-home",
                        str(database),
                        "--sample-seconds",
                        "0.001",
                        "--full-scan",
                    ]
                )
            self.assertEqual(code, cli.EXIT_OK)
            self.assertEqual(seen, [True])

    def test_plan_cross_boundary_refusal_has_safety_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            with (
                patch(
                    "codex_storage_doctor.planning.cross_boundary_reason",
                    return_value="synthetic native-side handoff",
                ),
                patch("sys.stderr", io.StringIO()),
            ):
                code = cli.main(
                    [
                        "plan",
                        "--database",
                        str(database),
                        "--mode",
                        "balanced",
                    ]
                )
            self.assertEqual(code, cli.EXIT_SAFETY_REFUSED)

    def test_verify_binds_manifest_database_and_exact_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            with patch(
                "codex_storage_doctor.planning.observed_codex_version",
                return_value=None,
            ):
                create_plan_for_test = create_plan(database, "balanced")
            result = cli.apply_plan(
                create_plan_for_test,
                create_plan_for_test["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(result["manifest"])

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
            self.assertEqual(code, cli.EXIT_OK)
            report = json.loads(stdout.getvalue())
            self.assertTrue(report["manifest_context"]["matches"])
            self.assertTrue(
                report["manifest_context"]["exact_trigger_state_matches"]
            )

            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TRIGGER codex_storage_doctor_v1_extra
                AFTER INSERT ON logs
                BEGIN SELECT 1; END
                """
            )
            connection.commit()
            connection.close()
            extra_stdout = io.StringIO()
            with (
                patch.object(cli, "sample_database", side_effect=sampled),
                patch.object(cli, "observed_codex_version", return_value=None),
                patch("sys.stdout", extra_stdout),
            ):
                extra_code = cli.main(
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
            self.assertEqual(extra_code, cli.EXIT_PARTIAL)
            extra_report = json.loads(extra_stdout.getvalue())
            self.assertFalse(extra_report["manifest_context"]["matches"])
            self.assertEqual(
                extra_report["inspection"][
                    "unexpected_doctor_trigger_count"
                ],
                1,
            )

            other_root = root / "other"
            other_root.mkdir()
            other_database = create_database(other_root)
            with (
                patch.object(cli, "sample_database", side_effect=sampled),
                patch.object(cli, "observed_codex_version", return_value=None),
                patch("sys.stdout", io.StringIO()),
            ):
                mismatch_code = cli.main(
                    [
                        "verify",
                        "--database",
                        str(other_database),
                        "--manifest",
                        str(manifest_path),
                        "--sample-seconds",
                        "0",
                    ]
                )
            self.assertEqual(mismatch_code, cli.EXIT_PARTIAL)

    def test_verify_refuses_replacement_with_expected_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "balanced")
            result = cli.apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(result["manifest"])
            replacement_root = root / "replacement"
            replacement_root.mkdir()
            replacement = create_database(replacement_root)
            database.unlink()
            replacement.replace(database)
            connection = sqlite3.connect(database)
            try:
                connection.execute(TRIGGER_SQL["balanced"])
                connection.commit()
            finally:
                connection.close()

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
            self.assertTrue(context["database_path_matches"])
            self.assertFalse(context["file_identity_matches"])
            self.assertFalse(context["database_matches"])
            self.assertFalse(context["matches"])

    def test_verify_refuses_unexpected_non_doctor_logs_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "maximum")
            result = cli.apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(result["manifest"])
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    """
                    CREATE TRIGGER synthetic_unrelated_logs_trigger
                    AFTER INSERT ON logs
                    BEGIN SELECT 1; END
                    """
                )
                connection.commit()
            finally:
                connection.close()

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
            self.assertFalse(context["base_schema_matches"])
            self.assertFalse(context["logs_trigger_set_matches"])
            self.assertFalse(context["exact_trigger_state_matches"])
            self.assertFalse(context["matches"])


if __name__ == "__main__":
    unittest.main()
