from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from codex_storage_doctor.models import ProcessObservation, ProcessScan
from codex_storage_doctor.sampling import sample_database


def build_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
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
            INSERT INTO logs (level, feedback_log_body, estimated_bytes)
            VALUES ('INFO', 'PRIVATE-SAMPLE-CANARY', 10);
            """
        )
        connection.commit()
    finally:
        connection.close()


class ScanSequence:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, database_paths: tuple[Path, ...]) -> ProcessScan:
        self.calls += 1
        return ProcessScan(
            status="ok",
            observations=(
                ProcessObservation(
                    pid=123,
                    surface="codex",
                    executable_basename="codex",
                    open_database_ids=("database-001",),
                    write_bytes=100 * self.calls,
                ),
            ),
            open_database_paths=database_paths,
        )


class SamplingTests(unittest.TestCase):
    def test_bounded_sample_reports_only_numeric_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_2.sqlite"
            build_database(database)
            scan_sequence = ScanSequence()

            def insert_during_interval(seconds: float) -> None:
                self.assertEqual(seconds, 5)
                connection = sqlite3.connect(database)
                try:
                    connection.execute(
                        """
                        INSERT INTO logs (
                            level, feedback_log_body, estimated_bytes
                        ) VALUES (?, ?, ?)
                        """,
                        ("A-FUTURE-PRIVATE-LEVEL", "SECOND-PRIVATE-CANARY", 25),
                    )
                    connection.commit()
                finally:
                    connection.close()

            result = sample_database(
                database,
                5,
                process_scan=scan_sequence,
                sleep_fn=insert_during_interval,
            )

            self.assertEqual(result.status, "ok")
            self.assertTrue(result.codex_process_observed)
            self.assertTrue(result.target_open_by_codex)
            self.assertTrue(result.logical_change_observed)
            self.assertEqual(result.delta.row_count, 1)
            self.assertEqual(result.delta.max_id, 1)
            self.assertEqual(result.delta.sqlite_sequence, 1)
            self.assertEqual(result.delta.estimated_bytes, 25)
            self.assertEqual(result.delta.process_write_bytes, 100)
            self.assertEqual(
                {item.level: item.rows for item in result.delta.levels}["OTHER"], 1
            )
            rendered = str(result.to_dict())
            self.assertNotIn("PRIVATE-SAMPLE-CANARY", rendered)
            self.assertNotIn("SECOND-PRIVATE-CANARY", rendered)
            self.assertNotIn("A-FUTURE-PRIVATE-LEVEL", rendered)
            self.assertIn("does not measure physical drive writes", rendered)

    def test_stable_idle_sample_is_bounded_not_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_2.sqlite"
            build_database(database)
            idle = ProcessScan(status="ok")
            result = sample_database(
                database,
                0,
                process_scan=idle,
                sleep_fn=lambda _seconds: None,
            )
            self.assertEqual(result.status, "ok")
            self.assertFalse(result.codex_process_observed)
            self.assertFalse(result.target_open_by_codex)
            self.assertFalse(result.logical_change_observed)
            self.assertEqual(result.delta.row_count, 0)
            self.assertNotIn("eliminated", str(result.to_dict()).lower())

    def test_generic_database_holder_is_not_reported_as_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_2.sqlite"
            build_database(database)
            generic_holder = ProcessScan(
                status="ok",
                observations=(
                    ProcessObservation(
                        pid=456,
                        surface="database-holder",
                        executable_basename="node",
                        is_codex=False,
                        open_database_ids=("database-001",),
                    ),
                ),
                held_database_paths=(database,),
            )
            result = sample_database(
                database,
                0,
                process_scan=generic_holder,
                sleep_fn=lambda _seconds: None,
            )
            self.assertFalse(result.codex_process_observed)
            self.assertFalse(result.target_open_by_codex)

    def test_invalid_duration_is_rejected_before_inspection(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative"):
            sample_database("/synthetic/not-opened.sqlite", -1)
        with self.assertRaisesRegex(ValueError, "one-day"):
            sample_database("/synthetic/not-opened.sqlite", 86_401)

    def test_explicit_full_scan_is_used_for_both_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "logs_2.sqlite"
            build_database(database)
            calls: list[bool] = []

            def inspect(path: str | Path, full_scan: bool):
                calls.append(full_scan)
                from codex_storage_doctor.sqlite_inspect import inspect_database

                return inspect_database(path, full_scan=full_scan)

            sample_database(
                database,
                0,
                process_scan=ProcessScan(status="ok"),
                full_scan=True,
                sleep_fn=lambda _seconds: None,
                inspect_fn=inspect,
            )
            self.assertEqual(calls, [True, True])


if __name__ == "__main__":
    unittest.main()
