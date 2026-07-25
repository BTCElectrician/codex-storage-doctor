from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import (
    active_process_scan,
    clear_process_scan,
    create_database,
    partial_process_scan,
)
from codex_storage_doctor.mitigation import (
    MutationRecoveryRequired,
    RollbackReconciliationRequired,
    SafetyGateError,
    _connect_writable,
    _seal_manifest,
    apply_plan,
    rollback,
    validate_manifest,
)
from codex_storage_doctor.models import ProcessObservation, ProcessScan
from codex_storage_doctor.planning import (
    PlanError,
    TRIGGER_NAMES,
    calculate_plan_digest,
    create_plan,
    cross_boundary_reason,
    doctor_triggers_connection,
    log_triggers_connection,
    read_only_connection,
    schema_fingerprint_connection,
    validate_plan_document,
)
from codex_storage_doctor.reports import read_json_object, write_private_json


class PlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.version_patch = patch(
            "codex_storage_doctor.planning.observed_codex_version",
            return_value=None,
        )
        self.version_patch.start()
        self.addCleanup(self.version_patch.stop)

    def test_plan_is_read_only_and_tamper_evident(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            before = database.read_bytes()
            plan = create_plan(database, "balanced")
            self.assertEqual(before, database.read_bytes())
            self.assertEqual(plan["mode"], "balanced")
            self.assertEqual(plan["suppresses"], ["TRACE", "DEBUG", "INFO"])
            validate_plan_document(plan)
            changed = dict(plan)
            changed["mode"] = "maximum"
            with self.assertRaises(PlanError):
                validate_plan_document(changed)

    def test_resealed_plan_cannot_redirect_target_or_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "balanced")
            victim = root / "existing-private-directory"
            victim.mkdir(mode=0o755)
            original_mode = victim.stat().st_mode & 0o777

            redirected = dict(plan)
            redirected["artifact_root"] = str(victim)
            digest = calculate_plan_digest(redirected)
            redirected["plan_digest"] = digest
            redirected["confirmation_token"] = f"APPLY-{digest[:12].upper()}"

            with self.assertRaisesRegex(SafetyGateError, "artifact root"):
                apply_plan(
                    redirected,
                    redirected["confirmation_token"],
                    process_scanner=clear_process_scan,
                )
            self.assertEqual(victim.stat().st_mode & 0o777, original_mode)
            self.assertEqual(tuple(victim.iterdir()), ())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "maximum")
            renamed = database.with_name("state_5.sqlite")
            database.rename(renamed)

            redirected = dict(plan)
            redirected["database"] = str(renamed)
            redirected["database_name"] = renamed.name
            redirected["artifact_root"] = str(
                renamed.parent / ".codex-storage-doctor" / "rollback"
            )
            digest = calculate_plan_digest(redirected)
            redirected["plan_digest"] = digest
            redirected["confirmation_token"] = f"APPLY-{digest[:12].upper()}"

            with self.assertRaisesRegex(SafetyGateError, "database target"):
                apply_plan(
                    redirected,
                    redirected["confirmation_token"],
                    process_scanner=clear_process_scan,
                )
            with sqlite3.connect(renamed) as connection:
                trigger_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
                ).fetchone()[0]
            self.assertEqual(trigger_count, 0)

    def test_plan_refuses_non_log_and_incompatible_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            incompatible = create_database(root, "logs_incompatible.sql")
            with self.assertRaises(PlanError):
                create_plan(incompatible, "balanced")
            with self.assertRaises(PlanError):
                create_plan(incompatible, "maximum")
            incompatible.rename(root / "state_5.sqlite")
            with self.assertRaises(PlanError):
                create_plan(root / "state_5.sqlite", "maximum")

    def test_read_only_connection_closes_after_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            with read_only_connection(database) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA query_only").fetchone(),
                    (1,),
                )
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_cross_boundary_detection(self) -> None:
        self.assertIsNotNone(
            cross_boundary_reason(
                Path(r"\\wsl.localhost\Ubuntu\home\example\logs_2.sqlite"),
                platform_name="Windows",
            )
        )
        self.assertIsNotNone(
            cross_boundary_reason(
                Path("/mnt/c/Users/Example/.codex/logs_2.sqlite"),
                platform_name="Linux",
                environ={"WSL_DISTRO_NAME": "Ubuntu"},
            )
        )
        self.assertIsNone(
            cross_boundary_reason(
                Path("/home/example/.codex/logs_2.sqlite"),
                platform_name="Linux",
                environ={"WSL_DISTRO_NAME": "Ubuntu"},
            )
        )

    def test_private_json_round_trip_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if os.name != "nt":
                root.chmod(0o755)
            path = root / "report.json"
            write_private_json(path, {"safe": True})
            self.assertEqual(read_json_object(path), {"safe": True})
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(root.stat().st_mode & 0o777, 0o755)

    def test_private_json_refuses_implicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_private_json(path, {"first": True})
            with self.assertRaises(FileExistsError):
                write_private_json(path, {"second": True})
            self.assertEqual(read_json_object(path), {"first": True})


class MitigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planning_version_patch = patch(
            "codex_storage_doctor.planning.observed_codex_version",
            return_value=None,
        )
        self.mitigation_version_patch = patch(
            "codex_storage_doctor.mitigation.observed_codex_version",
            return_value=None,
        )
        self.planning_version_patch.start()
        self.mitigation_version_patch.start()
        self.addCleanup(self.planning_version_patch.stop)
        self.addCleanup(self.mitigation_version_patch.stop)

    def _seed(self, database: Path) -> None:
        connection = sqlite3.connect(database)
        for level in ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "NOTICE"):
            connection.execute(
                """
                INSERT INTO logs (
                    ts, ts_nanos, level, target, feedback_log_body,
                    estimated_bytes
                ) VALUES (1, 0, ?, 'synthetic', ?, 10)
                """,
                (level, f"PRIVATE-CANARY-{level}"),
            )
        connection.commit()
        connection.close()

    def test_balanced_apply_backup_idempotency_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            self._seed(database)
            plan = create_plan(database, "balanced")
            result = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            self.assertEqual(result["status"], "applied")

            backup = Path(result["backup"])
            backup_connection = sqlite3.connect(backup)
            backup_triggers = backup_connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
            ).fetchone()[0]
            backup_connection.close()
            self.assertEqual(backup_triggers, 0)

            connection = sqlite3.connect(database)
            for level in ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "NOTICE"):
                connection.execute(
                    """
                    INSERT INTO logs (
                        ts, ts_nanos, level, target, feedback_log_body,
                        estimated_bytes
                    ) VALUES (2, 0, ?, 'synthetic', 'AFTER', 5)
                    """,
                    (level,),
                )
            connection.commit()
            levels = [
                row[0]
                for row in connection.execute(
                    "SELECT level FROM logs WHERE ts=2 ORDER BY id"
                )
            ]
            connection.close()
            self.assertEqual(levels, ["WARN", "ERROR", "NOTICE"])

            repeat = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            self.assertEqual(repeat["status"], "already_applied")
            self.assertFalse(repeat["changed"])

            manifest_path = Path(result["manifest"])
            manifest = read_json_object(manifest_path)
            validate_manifest(manifest)
            reversed_result = rollback(
                manifest,
                manifest["rollback_token"],
                process_scanner=clear_process_scan,
                manifest_path=manifest_path,
            )
            self.assertTrue(reversed_result["changed"])
            connection = sqlite3.connect(database)
            trigger_count = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name=?",
                (TRIGGER_NAMES["balanced"],),
            ).fetchone()[0]
            connection.close()
            self.assertEqual(trigger_count, 0)

    def test_maximum_blocks_all_levels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "maximum")
            apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            connection = sqlite3.connect(database)
            connection.execute(
                """
                INSERT INTO logs (
                    ts, ts_nanos, level, target, feedback_log_body,
                    estimated_bytes
                ) VALUES (1, 0, 'ERROR', 'synthetic', 'BLOCKED', 7)
                """
            )
            connection.commit()
            count = connection.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
            connection.close()
            self.assertEqual(count, 0)

    def test_active_and_partial_process_scans_refuse_without_trigger(self) -> None:
        for scanner in (active_process_scan, partial_process_scan):
            with self.subTest(scanner=scanner.__name__):
                with tempfile.TemporaryDirectory() as directory:
                    database = create_database(Path(directory))
                    plan = create_plan(database, "balanced")
                    with self.assertRaises(SafetyGateError):
                        apply_plan(
                            plan,
                            plan["confirmation_token"],
                            process_scanner=scanner,
                        )
                    connection = sqlite3.connect(database)
                    count = connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
                    ).fetchone()[0]
                    connection.close()
                    self.assertEqual(count, 0)

    def test_stale_schema_refuses_before_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "balanced")
            connection = sqlite3.connect(database)
            connection.execute("ALTER TABLE logs ADD COLUMN changed INTEGER")
            connection.commit()
            connection.close()
            with self.assertRaises(SafetyGateError):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )
            artifact_root = Path(plan["artifact_root"])
            self.assertFalse(artifact_root.exists())

    def test_conflicting_log_trigger_refuses_planning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TRIGGER synthetic_conflict
                BEFORE INSERT ON logs
                BEGIN
                  SELECT RAISE(IGNORE);
                END
                """
            )
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(PlanError, "conflicting"):
                create_plan(database, "balanced")

    def test_additional_trigger_after_plan_refuses_even_if_exact_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TRIGGER codex_storage_doctor_v1_balanced
                BEFORE INSERT ON logs
                WHEN UPPER(COALESCE(NEW.level, '')) IN ('TRACE', 'DEBUG', 'INFO')
                BEGIN
                  SELECT RAISE(IGNORE);
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER codex_storage_doctor_v1_extra
                AFTER INSERT ON logs
                BEGIN
                  SELECT 1;
                END
                """
            )
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(SafetyGateError, "conflicting"):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )

    def test_rows_added_after_plan_are_preserved_in_fresh_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            connection = sqlite3.connect(database)
            connection.execute(
                """
                INSERT INTO logs (
                    ts, ts_nanos, level, target, feedback_log_body,
                    estimated_bytes
                ) VALUES (3, 0, 'WARN', 'synthetic', 'LATE-PRIVATE-ROW', 12)
                """
            )
            connection.commit()
            connection.close()
            result = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            backup = sqlite3.connect(result["backup"])
            try:
                count = backup.execute(
                    "SELECT COUNT(*) FROM logs WHERE ts = 3"
                ).fetchone()[0]
            finally:
                backup.close()
            self.assertEqual(count, 1)

    def test_writable_open_never_creates_a_missing_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "logs_2.sqlite"
            with self.assertRaises(SafetyGateError):
                _connect_writable(missing)
            self.assertFalse(missing.exists())

    def test_version_change_refuses_before_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            with patch(
                "codex_storage_doctor.planning.observed_codex_version",
                return_value="codex-cli 0.145.0",
            ):
                plan = create_plan(database, "balanced")
            with (
                patch(
                    "codex_storage_doctor.mitigation.observed_codex_version",
                    return_value="codex-cli 0.146.0",
                ),
                self.assertRaisesRegex(SafetyGateError, "version changed"),
            ):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )
            self.assertFalse(Path(plan["artifact_root"]).exists())

    def test_known_plan_version_refuses_when_current_version_is_unavailable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            with patch(
                "codex_storage_doctor.planning.observed_codex_version",
                return_value="codex-cli 0.145.0",
            ):
                plan = create_plan(database, "balanced")
            with (
                patch(
                    "codex_storage_doctor.mitigation.observed_codex_version",
                    return_value=None,
                ),
                self.assertRaisesRegex(SafetyGateError, "unavailable"),
            ):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )
            self.assertFalse(Path(plan["artifact_root"]).exists())

    def test_manifest_lifecycle_fields_are_tamper_evident(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            result = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest = read_json_object(Path(result["manifest"]))
            validate_manifest(manifest)
            manifest["status"] = "rolled_back"
            with self.assertRaisesRegex(SafetyGateError, "digest mismatch"):
                validate_manifest(manifest)

    def test_resealed_manifest_cannot_redirect_rollback_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "balanced")
            applied = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(applied["manifest"])
            manifest = read_json_object(manifest_path)
            victim = root / "existing-private-directory"
            victim.mkdir(mode=0o755)
            original_mode = victim.stat().st_mode & 0o777

            redirected = dict(manifest)
            redirected["backup_path"] = str(
                victim / "logs-before-apply.sqlite"
            )
            _seal_manifest(redirected)

            with self.assertRaisesRegex(
                SafetyGateError,
                "rollback artifact",
            ):
                rollback(
                    redirected,
                    redirected["rollback_token"],
                    process_scanner=clear_process_scan,
                    manifest_path=manifest_path,
                )
            self.assertEqual(victim.stat().st_mode & 0o777, original_mode)
            self.assertEqual(tuple(victim.iterdir()), ())
            with sqlite3.connect(database) as connection:
                trigger_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
                ).fetchone()[0]
            self.assertEqual(trigger_count, 1)

            missing_backup_path = dict(manifest)
            missing_backup_path.pop("backup_path")
            _seal_manifest(missing_backup_path)
            with self.assertRaisesRegex(
                SafetyGateError,
                "backup path",
            ):
                validate_manifest(missing_backup_path)

    def test_post_commit_manifest_failure_surfaces_durable_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            real_write = write_private_json

            def fail_final_manifest(path, value, *, overwrite=False):
                if overwrite:
                    raise OSError("synthetic finalization failure")
                return real_write(path, value, overwrite=overwrite)

            with (
                patch(
                    "codex_storage_doctor.mitigation.write_private_json",
                    side_effect=fail_final_manifest,
                ),
                self.assertRaises(MutationRecoveryRequired) as caught,
            ):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )

            recovery = caught.exception.result
            self.assertEqual(
                recovery["status"],
                "mutation_recovery_required",
            )
            self.assertTrue(recovery["mutation_occurred"])
            self.assertTrue(recovery["recovery_required"])
            self.assertTrue(recovery["durable_manifest_verified"])
            manifest = read_json_object(Path(recovery["manifest"]))
            self.assertEqual(manifest["status"], "prepared")
            self.assertEqual(
                recovery["rollback_token"],
                manifest["rollback_token"],
            )
            validate_manifest(manifest)
            connection = sqlite3.connect(database)
            try:
                installed = connection.execute(
                    """
                    SELECT COUNT(*) FROM sqlite_master
                    WHERE type='trigger' AND name=?
                    """,
                    (TRIGGER_NAMES["balanced"],),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(installed, 1)

    def test_post_commit_verification_failure_surfaces_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            calls = 0

            def fail_post_commit_verification(connection):
                nonlocal calls
                calls += 1
                if calls == 3:
                    return {}
                return log_triggers_connection(connection)

            with (
                patch(
                    "codex_storage_doctor.mitigation.log_triggers_connection",
                    side_effect=fail_post_commit_verification,
                ),
                self.assertRaises(MutationRecoveryRequired) as caught,
            ):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )

            recovery = caught.exception.result
            self.assertEqual(recovery["failure_stage"], "post_commit")
            self.assertEqual(recovery["failure_code"], "operation_failed")
            self.assertTrue(Path(recovery["manifest"]).is_file())
            self.assertTrue(Path(recovery["backup"]).is_file())
            manifest = read_json_object(Path(recovery["manifest"]))
            self.assertEqual(
                recovery["rollback_token"],
                manifest["rollback_token"],
            )

    def test_post_commit_schema_race_requires_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            calls = 0

            def changed_after_commit(connection):
                nonlocal calls
                calls += 1
                if calls == 3:
                    racer = sqlite3.connect(database)
                    try:
                        racer.execute(
                            "ALTER TABLE logs ADD COLUMN synthetic_race INTEGER"
                        )
                        racer.commit()
                    finally:
                        racer.close()
                return schema_fingerprint_connection(connection)

            with (
                patch(
                    "codex_storage_doctor.mitigation.schema_fingerprint_connection",
                    side_effect=changed_after_commit,
                ),
                self.assertRaises(MutationRecoveryRequired) as caught,
            ):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )

            recovery = caught.exception.result
            self.assertTrue(recovery["mutation_occurred"])
            self.assertTrue(recovery["recovery_required"])
            self.assertEqual(recovery["failure_stage"], "post_commit")
            connection = sqlite3.connect(database)
            try:
                installed = connection.execute(
                    """
                    SELECT COUNT(*) FROM sqlite_master
                    WHERE type='trigger' AND name=?
                    """,
                    (TRIGGER_NAMES["balanced"],),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(installed, 1)

    def test_post_commit_unrelated_logs_trigger_race_requires_recovery(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "maximum")
            calls = 0

            def extra_trigger_after_commit(connection):
                nonlocal calls
                calls += 1
                if calls == 3:
                    racer = sqlite3.connect(database)
                    try:
                        racer.execute(
                            "CREATE TRIGGER synthetic_unrelated "
                            "BEFORE INSERT ON logs BEGIN SELECT 1; END"
                        )
                        racer.commit()
                    finally:
                        racer.close()
                return log_triggers_connection(connection)

            with (
                patch(
                    "codex_storage_doctor.mitigation.log_triggers_connection",
                    side_effect=extra_trigger_after_commit,
                ),
                self.assertRaises(MutationRecoveryRequired) as caught,
            ):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )

            recovery = caught.exception.result
            self.assertTrue(recovery["mutation_occurred"])
            self.assertTrue(recovery["recovery_required"])
            self.assertEqual(recovery["failure_stage"], "post_commit")

    def test_post_commit_doctor_trigger_on_other_table_requires_recovery(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            calls = 0

            def extra_doctor_trigger_after_commit(connection):
                nonlocal calls
                calls += 1
                if calls == 3:
                    racer = sqlite3.connect(database)
                    try:
                        racer.executescript(
                            """
                            CREATE TABLE synthetic_other (id INTEGER);
                            CREATE TRIGGER codex_storage_doctor_v1_other
                            BEFORE INSERT ON synthetic_other
                            BEGIN
                                SELECT 1;
                            END;
                            """
                        )
                        racer.commit()
                    finally:
                        racer.close()
                return doctor_triggers_connection(connection)

            with (
                patch(
                    "codex_storage_doctor.mitigation.doctor_triggers_connection",
                    side_effect=extra_doctor_trigger_after_commit,
                ),
                self.assertRaises(MutationRecoveryRequired) as caught,
            ):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )

            recovery = caught.exception.result
            self.assertTrue(recovery["mutation_occurred"])
            self.assertTrue(recovery["recovery_required"])
            self.assertEqual(recovery["failure_stage"], "post_commit")

    def test_post_commit_connection_close_failure_surfaces_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "maximum")
            real_connect = _connect_writable

            class CloseFailureConnection:
                def __init__(self, path: Path) -> None:
                    self.connection = real_connect(path)

                def __getattr__(self, name):
                    return getattr(self.connection, name)

                def close(self) -> None:
                    self.connection.close()
                    raise OSError("synthetic close failure")

            with (
                patch(
                    "codex_storage_doctor.mitigation._connect_writable",
                    side_effect=CloseFailureConnection,
                ),
                self.assertRaises(MutationRecoveryRequired) as caught,
            ):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )

            recovery = caught.exception.result
            self.assertTrue(recovery["mutation_occurred"])
            self.assertEqual(
                recovery["durable_manifest_status"],
                "applied",
            )
            manifest = read_json_object(Path(recovery["manifest"]))
            self.assertEqual(manifest["status"], "applied")
            self.assertEqual(
                recovery["rollback_token"],
                manifest["rollback_token"],
            )

    def test_apply_commit_raise_after_success_uses_verified_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            real_connect = _connect_writable

            class RaiseAfterCommitConnection:
                def __init__(self, path: Path) -> None:
                    self.connection = real_connect(path)

                def __getattr__(self, name):
                    return getattr(self.connection, name)

                def execute(self, sql, *args):
                    result = self.connection.execute(sql, *args)
                    if sql == "COMMIT":
                        raise sqlite3.OperationalError(
                            "synthetic error after commit"
                        )
                    return result

            with (
                patch(
                    "codex_storage_doctor.mitigation._connect_writable",
                    side_effect=RaiseAfterCommitConnection,
                ),
                self.assertRaises(MutationRecoveryRequired) as caught,
            ):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )

            recovery = caught.exception.result
            self.assertEqual(recovery["commit_outcome"], "verified_committed")
            self.assertTrue(recovery["mutation_occurred"])
            self.assertEqual(recovery["failure_stage"], "commit_outcome")

    def test_apply_ambiguous_commit_outcome_never_reports_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "maximum")
            real_connect = _connect_writable

            class RaiseAfterCommitConnection:
                def __init__(self, path: Path) -> None:
                    self.connection = real_connect(path)

                def __getattr__(self, name):
                    return getattr(self.connection, name)

                def execute(self, sql, *args):
                    result = self.connection.execute(sql, *args)
                    if sql == "COMMIT":
                        raise sqlite3.OperationalError("synthetic ambiguity")
                    return result

            with (
                patch(
                    "codex_storage_doctor.mitigation._connect_writable",
                    side_effect=RaiseAfterCommitConnection,
                ),
                patch(
                    "codex_storage_doctor.mitigation._apply_commit_outcome",
                    return_value="ambiguous",
                ),
                self.assertRaises(MutationRecoveryRequired) as caught,
            ):
                apply_plan(
                    plan,
                    plan["confirmation_token"],
                    process_scanner=clear_process_scan,
                )

            recovery = caught.exception.result
            self.assertEqual(recovery["commit_outcome"], "ambiguous")
            self.assertTrue(recovery["commit_may_have_succeeded"])
            self.assertIsNone(recovery["mutation_occurred"])

    def test_final_gate_ignores_only_own_writable_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            calls = 0

            def self_only_at_final(*_args, **_kwargs):
                nonlocal calls
                calls += 1
                if calls < 3:
                    return clear_process_scan()
                return ProcessScan(
                    status="ok",
                    observations=(
                        ProcessObservation(
                            pid=os.getpid(),
                            surface="database-holder",
                            executable_basename="python",
                            is_codex=False,
                            open_database_ids=("database-001",),
                        ),
                    ),
                    held_database_paths=(database,),
                )

            result = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=self_only_at_final,
            )
            self.assertEqual(result["status"], "applied")

            other = ProcessObservation(
                pid=os.getpid() + 1,
                surface="database-holder",
                executable_basename="sqlite3",
                is_codex=False,
                open_database_ids=("database-001",),
            )
            second_root = Path(directory) / "second"
            second_root.mkdir()
            second_database = create_database(second_root)
            second_plan = create_plan(second_database, "maximum")
            second_calls = 0

            def other_at_final(*_args, **_kwargs):
                nonlocal second_calls
                second_calls += 1
                if second_calls < 3:
                    return clear_process_scan()
                return ProcessScan(
                    status="ok",
                    observations=(
                        ProcessObservation(
                            pid=os.getpid(),
                            surface="database-holder",
                            executable_basename="python",
                            is_codex=False,
                            open_database_ids=("database-001",),
                        ),
                        other,
                    ),
                    held_database_paths=(second_database,),
                )

            with self.assertRaisesRegex(SafetyGateError, "database is open"):
                apply_plan(
                    second_plan,
                    second_plan["confirmation_token"],
                    process_scanner=other_at_final,
                )
            connection = sqlite3.connect(second_database)
            try:
                trigger_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(trigger_count, 0)

    def test_rollback_refuses_replaced_database_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = create_database(root)
            plan = create_plan(database, "balanced")
            result = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest = read_json_object(Path(result["manifest"]))
            replacement_root = root / "replacement"
            replacement_root.mkdir()
            replacement = create_database(replacement_root)
            database.unlink()
            replacement.replace(database)
            with self.assertRaisesRegex(SafetyGateError, "identity"):
                rollback(
                    manifest,
                    manifest["rollback_token"],
                    process_scanner=clear_process_scan,
                )

    def test_post_commit_rollback_failure_surfaces_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            applied = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(applied["manifest"])
            manifest = read_json_object(manifest_path)
            real_write = write_private_json

            def fail_manifest_advance(path, value, *, overwrite=False):
                if overwrite:
                    raise OSError("synthetic rollback finalization failure")
                return real_write(path, value, overwrite=overwrite)

            with (
                patch(
                    "codex_storage_doctor.mitigation.write_private_json",
                    side_effect=fail_manifest_advance,
                ),
                self.assertRaises(RollbackReconciliationRequired) as caught,
            ):
                rollback(
                    manifest,
                    manifest["rollback_token"],
                    process_scanner=clear_process_scan,
                    manifest_path=manifest_path,
                )

            recovery = caught.exception.result
            self.assertTrue(recovery["rollback_occurred"])
            self.assertTrue(recovery["reconciliation_required"])
            durable = read_json_object(manifest_path)
            self.assertEqual(durable["status"], "applied")
            self.assertEqual(
                recovery["rollback_token"],
                durable["rollback_token"],
            )
            connection = sqlite3.connect(database)
            try:
                trigger_count = connection.execute(
                    """
                    SELECT COUNT(*) FROM sqlite_master
                    WHERE type='trigger' AND name=?
                    """,
                    (TRIGGER_NAMES["balanced"],),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(trigger_count, 0)

            reconciled = rollback(
                durable,
                durable["rollback_token"],
                process_scanner=clear_process_scan,
                manifest_path=manifest_path,
            )
            self.assertEqual(reconciled["status"], "already_rolled_back")
            self.assertTrue(reconciled["manifest_reconciled"])
            self.assertEqual(
                read_json_object(manifest_path)["status"],
                "rolled_back",
            )

    def test_post_commit_rollback_close_failure_surfaces_reconciliation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "maximum")
            applied = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(applied["manifest"])
            manifest = read_json_object(manifest_path)
            real_connect = _connect_writable

            class CloseFailureConnection:
                def __init__(self, path: Path) -> None:
                    self.connection = real_connect(path)

                def __getattr__(self, name):
                    return getattr(self.connection, name)

                def close(self) -> None:
                    self.connection.close()
                    raise OSError("synthetic rollback close failure")

            with (
                patch(
                    "codex_storage_doctor.mitigation._connect_writable",
                    side_effect=CloseFailureConnection,
                ),
                self.assertRaises(RollbackReconciliationRequired) as caught,
            ):
                rollback(
                    manifest,
                    manifest["rollback_token"],
                    process_scanner=clear_process_scan,
                    manifest_path=manifest_path,
                )

            recovery = caught.exception.result
            self.assertTrue(recovery["rollback_occurred"])
            self.assertEqual(
                recovery["durable_manifest_status"],
                "applied",
            )

    def test_rollback_commit_raise_after_success_uses_verified_outcome(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            applied = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(applied["manifest"])
            manifest = read_json_object(manifest_path)
            real_connect = _connect_writable

            class RaiseAfterCommitConnection:
                def __init__(self, path: Path) -> None:
                    self.connection = real_connect(path)

                def __getattr__(self, name):
                    return getattr(self.connection, name)

                def execute(self, sql, *args):
                    result = self.connection.execute(sql, *args)
                    if sql == "COMMIT":
                        raise sqlite3.OperationalError(
                            "synthetic error after rollback commit"
                        )
                    return result

            with (
                patch(
                    "codex_storage_doctor.mitigation._connect_writable",
                    side_effect=RaiseAfterCommitConnection,
                ),
                self.assertRaises(RollbackReconciliationRequired) as caught,
            ):
                rollback(
                    manifest,
                    manifest["rollback_token"],
                    process_scanner=clear_process_scan,
                    manifest_path=manifest_path,
                )

            recovery = caught.exception.result
            self.assertEqual(recovery["commit_outcome"], "verified_committed")
            self.assertTrue(recovery["rollback_occurred"])
            self.assertEqual(recovery["failure_stage"], "commit_outcome")

    def test_rollback_ambiguous_commit_outcome_never_reports_refusal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "maximum")
            applied = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(applied["manifest"])
            manifest = read_json_object(manifest_path)
            real_connect = _connect_writable

            class RaiseAfterCommitConnection:
                def __init__(self, path: Path) -> None:
                    self.connection = real_connect(path)

                def __getattr__(self, name):
                    return getattr(self.connection, name)

                def execute(self, sql, *args):
                    result = self.connection.execute(sql, *args)
                    if sql == "COMMIT":
                        raise sqlite3.OperationalError("synthetic ambiguity")
                    return result

            with (
                patch(
                    "codex_storage_doctor.mitigation._connect_writable",
                    side_effect=RaiseAfterCommitConnection,
                ),
                patch(
                    "codex_storage_doctor.mitigation._rollback_commit_outcome",
                    return_value="ambiguous",
                ),
                self.assertRaises(RollbackReconciliationRequired) as caught,
            ):
                rollback(
                    manifest,
                    manifest["rollback_token"],
                    process_scanner=clear_process_scan,
                    manifest_path=manifest_path,
                )

            recovery = caught.exception.result
            self.assertEqual(recovery["commit_outcome"], "ambiguous")
            self.assertTrue(recovery["commit_may_have_succeeded"])
            self.assertIsNone(recovery["rollback_occurred"])

    def test_post_commit_rollback_verification_failure_is_reconciliation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            applied = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(applied["manifest"])
            manifest = read_json_object(manifest_path)
            calls = 0

            def fail_post_commit_verification(connection):
                nonlocal calls
                calls += 1
                if calls == 3:
                    return {"synthetic_unexpected": "synthetic"}
                return doctor_triggers_connection(connection)

            with (
                patch(
                    "codex_storage_doctor.mitigation.doctor_triggers_connection",
                    side_effect=fail_post_commit_verification,
                ),
                self.assertRaises(RollbackReconciliationRequired) as caught,
            ):
                rollback(
                    manifest,
                    manifest["rollback_token"],
                    process_scanner=clear_process_scan,
                    manifest_path=manifest_path,
                )

            self.assertTrue(caught.exception.result["rollback_occurred"])
            self.assertEqual(
                read_json_object(manifest_path)["status"],
                "applied",
            )

    def test_rollback_refuses_unexpected_doctor_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            result = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest = read_json_object(Path(result["manifest"]))
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
            with self.assertRaisesRegex(SafetyGateError, "unexpected"):
                rollback(
                    manifest,
                    manifest["rollback_token"],
                    process_scanner=clear_process_scan,
                    manifest_path=Path(result["manifest"]),
                )

    def test_already_absent_trigger_reconciles_manifest_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            plan = create_plan(database, "balanced")
            result = apply_plan(
                plan,
                plan["confirmation_token"],
                process_scanner=clear_process_scan,
            )
            manifest_path = Path(result["manifest"])
            manifest = read_json_object(manifest_path)
            connection = sqlite3.connect(database)
            connection.execute(
                f'DROP TRIGGER "{TRIGGER_NAMES["balanced"]}"'
            )
            connection.commit()
            connection.close()
            rollback_result = rollback(
                manifest,
                manifest["rollback_token"],
                process_scanner=clear_process_scan,
                manifest_path=manifest_path,
            )
            self.assertEqual(
                rollback_result["status"],
                "already_rolled_back",
            )
            self.assertTrue(rollback_result["manifest_reconciled"])
            reconciled = read_json_object(manifest_path)
            self.assertEqual(reconciled["status"], "rolled_back")
            validate_manifest(reconciled)


if __name__ == "__main__":
    unittest.main()
