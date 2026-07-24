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
    SafetyGateError,
    _connect_writable,
    apply_plan,
    rollback,
    validate_manifest,
)
from codex_storage_doctor.planning import (
    PlanError,
    TRIGGER_NAMES,
    calculate_plan_digest,
    create_plan,
    cross_boundary_reason,
    read_only_connection,
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
