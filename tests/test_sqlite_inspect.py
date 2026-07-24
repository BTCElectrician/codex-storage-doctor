from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from codex_storage_doctor.privacy import (
    PrivacyViolation,
    assert_privacy_safe,
)
from codex_storage_doctor.sqlite_inspect import inspect_database


FIXTURES = Path(__file__).parent / "fixtures"


PRIVATE_CANARIES = (
    "PRIVATE-BODY-CANARY",
    "PRIVATE-TARGET-CANARY",
    "PRIVATE-THREAD-CANARY",
    "PRIVATE-PROCESS-CANARY",
    "PRIVATE-FILE-CANARY",
    "PRIVATE-MODULE-CANARY",
    "PRIVATE-UNKNOWN-LEVEL",
)


def build_database(path: Path, *, compatible: bool = True) -> None:
    connection = sqlite3.connect(path)
    try:
        if compatible:
            connection.executescript(
                """
                CREATE TABLE logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL DEFAULT 0,
                    ts_nanos INTEGER NOT NULL DEFAULT 0,
                    level TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT 'synthetic',
                    feedback_log_body TEXT,
                    module_path TEXT,
                    file TEXT,
                    line INTEGER,
                    thread_id TEXT,
                    process_uuid TEXT,
                    estimated_bytes INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            rows = [
                ("trace", 10),
                ("DEBUG", 20),
                ("INFO", 30),
                ("WARN", 40),
                ("ERROR", 50),
                ("PRIVATE-UNKNOWN-LEVEL", 60),
            ]
            connection.executemany(
                """
                INSERT INTO logs (
                    level, target, feedback_log_body, module_path, file,
                    thread_id, process_uuid, estimated_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        level,
                        PRIVATE_CANARIES[1],
                        PRIVATE_CANARIES[0],
                        PRIVATE_CANARIES[5],
                        PRIVATE_CANARIES[4],
                        PRIVATE_CANARIES[2],
                        PRIVATE_CANARIES[3],
                        estimated,
                    )
                    for level, estimated in rows
                ],
            )
        else:
            connection.execute(
                "CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT)"
            )
            connection.execute(
                "INSERT INTO logs (message) VALUES (?)", (PRIVATE_CANARIES[0],)
            )
        connection.commit()
    finally:
        connection.close()


class SQLiteInspectionTests(unittest.TestCase):
    def test_supported_historical_and_future_fixtures(self) -> None:
        for fixture in ("logs_v1.sql", "logs_v2.sql", "logs_future.sql"):
            with self.subTest(fixture=fixture):
                with tempfile.TemporaryDirectory() as temporary:
                    database = Path(temporary) / "logs_2.sqlite"
                    connection = sqlite3.connect(database)
                    connection.executescript(
                        (FIXTURES / fixture).read_text(encoding="utf-8")
                    )
                    connection.commit()
                    connection.close()
                    result = inspect_database(database)
                    self.assertEqual(result.status, "ok")
                    self.assertTrue(result.schema_supported)

    def test_high_water_mark_is_distinct_from_retained_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_2.sqlite"
            build_database(database)
            connection = sqlite3.connect(database)
            connection.execute("DELETE FROM logs WHERE id < 6")
            connection.commit()
            connection.close()
            result = inspect_database(database)
            self.assertEqual(result.row_count, 1)
            self.assertEqual(result.max_id, 6)
            self.assertEqual(result.sqlite_sequence, 6)

    def test_allowlisted_aggregates_never_emit_private_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_2.sqlite"
            build_database(database)
            before = database.read_bytes()

            result = inspect_database(database)

            self.assertEqual(result.status, "ok")
            self.assertTrue(result.quick_check_ok)
            self.assertTrue(result.schema_supported)
            self.assertEqual(result.row_count, 6)
            self.assertEqual(result.max_id, 6)
            self.assertEqual(result.sqlite_sequence, 6)
            self.assertEqual(result.estimated_bytes, 210)
            self.assertEqual(
                {item.level: item.rows for item in result.level_aggregates},
                {
                    "TRACE": 1,
                    "DEBUG": 1,
                    "INFO": 1,
                    "WARN": 1,
                    "ERROR": 1,
                    "OTHER": 1,
                },
            )
            report = result.to_dict()
            assert_privacy_safe(report, forbidden_values=PRIVATE_CANARIES)
            rendered = json.dumps(report, sort_keys=True)
            for canary in PRIVATE_CANARIES:
                self.assertNotIn(canary, rendered)
            self.assertNotIn(str(database), rendered)
            self.assertEqual(database.read_bytes(), before)

    def test_schema_metadata_is_allowlisted_and_path_values_are_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_2.sqlite"
            build_database(database)
            private_column = "client_/Users/synthetic/private"
            private_type = "TYPE_/Users/synthetic/type"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    f'ALTER TABLE logs ADD COLUMN "{private_column}" '
                    f'"{private_type}"'
                )
                connection.commit()
            finally:
                connection.close()

            report = inspect_database(database).to_dict()
            rendered = json.dumps(report, sort_keys=True)
            self.assertEqual(
                report["unrecognized_schema_column_count"],
                1,
            )
            self.assertNotIn(private_column, rendered)
            self.assertNotIn(private_type, rendered)
            assert_privacy_safe(report, forbid_absolute_paths=True)
            with self.assertRaisesRegex(
                PrivacyViolation,
                "absolute path",
            ):
                assert_privacy_safe(
                    {"safe_key": f"prefix {private_column} suffix"},
                    forbid_absolute_paths=True,
                )
            for canary in (
                "/tmp",
                "/.codex",
                r"C:\Users\synthetic",
                r"\\server\private",
                "//server/share/private",
                "file:///Users/synthetic/private",
                "file:///C:/Users/synthetic/private",
                "/",
            ):
                with self.subTest(canary=canary), self.assertRaises(
                    PrivacyViolation
                ):
                    assert_privacy_safe(
                        {"safe_key": canary},
                        forbid_absolute_paths=True,
                    )
            assert_privacy_safe(
                {"safe_key": "https://example.com/support"},
                forbid_absolute_paths=True,
            )

    def test_incompatible_schema_fails_closed_without_body_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_1.sqlite"
            build_database(database, compatible=False)
            result = inspect_database(database)
            self.assertEqual(result.status, "error")
            self.assertFalse(result.schema_supported)
            self.assertIsNone(result.row_count)
            assert_privacy_safe(result.to_dict(), forbidden_values=PRIVATE_CANARIES)

    def test_altered_doctor_trigger_is_not_reported_as_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_2.sqlite"
            build_database(database)
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    CREATE TRIGGER private_trigger_name
                    BEFORE INSERT ON logs BEGIN SELECT RAISE(IGNORE); END;
                    CREATE TRIGGER codex_storage_doctor_v1_balanced
                    BEFORE INSERT ON logs
                    WHEN UPPER(NEW.level) IN ('TRACE', 'DEBUG', 'INFO')
                    BEGIN SELECT RAISE(IGNORE); END;
                    """
                )
                connection.commit()
            finally:
                connection.close()
            result = inspect_database(database)
            self.assertEqual(result.doctor_triggers, ())
            self.assertEqual(
                result.altered_doctor_triggers,
                ("codex_storage_doctor_v1_balanced",),
            )
            self.assertEqual(result.status, "error")
            self.assertIn(
                "doctor_trigger_sql_mismatch",
                [finding.code for finding in result.findings],
            )
            self.assertNotIn("private_trigger_name", json.dumps(result.to_dict()))

    def test_unexpected_doctor_trigger_is_counted_without_name_or_sql(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_2.sqlite"
            build_database(database)
            private_name = (
                "codex_storage_doctor_v1_SYNTHETIC_PRIVATE_TRIGGER_NAME"
            )
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    f"""
                    CREATE TRIGGER {private_name}
                    AFTER INSERT ON logs
                    BEGIN SELECT 1; END
                    """
                )
                connection.commit()
            finally:
                connection.close()
            result = inspect_database(database)
            rendered = json.dumps(result.to_dict())
            self.assertEqual(result.unexpected_doctor_trigger_count, 1)
            self.assertEqual(result.status, "error")
            self.assertIn(
                "unexpected_doctor_trigger",
                [finding.code for finding in result.findings],
            )
            self.assertNotIn(private_name, rendered)

    def test_full_scan_threshold_and_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_2.sqlite"
            build_database(database)
            with mock.patch(
                "codex_storage_doctor.sqlite_inspect.FULL_SCAN_THRESHOLD_BYTES", 1
            ):
                bounded = inspect_database(database)
                explicit = inspect_database(database, full_scan=True)
            self.assertFalse(bounded.full_scan_performed)
            self.assertIsNone(bounded.row_count)
            self.assertIn("full_scan_skipped", [item.code for item in bounded.findings])
            self.assertTrue(explicit.full_scan_performed)
            self.assertEqual(explicit.row_count, 6)

    def test_readonly_cantinit_is_a_partial_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_2.sqlite"
            build_database(database)
            error = sqlite3.OperationalError("synthetic")
            with (
                mock.patch(
                    "codex_storage_doctor.sqlite_inspect.sqlite3.connect",
                    side_effect=error,
                ),
                mock.patch(
                    "codex_storage_doctor.sqlite_inspect._is_readonly_cantinit",
                    return_value=True,
                ),
            ):
                result = inspect_database(database)
            self.assertEqual(result.status, "partial")
            self.assertTrue(result.partial)
            self.assertEqual(result.findings[0].code, "wal_readonly_cantinit")
            self.assertNotIn("synthetic", json.dumps(result.to_dict()))


if __name__ == "__main__":
    unittest.main()
