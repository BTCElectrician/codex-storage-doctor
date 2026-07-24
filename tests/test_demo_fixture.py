from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.create_demo_fixture import create_fixture


class DemoFixtureTests(unittest.TestCase):
    def test_fixture_is_synthetic_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            current, stale = create_fixture(root)
            self.assertTrue(current.is_file())
            self.assertTrue(stale.is_file())
            connection = sqlite3.connect(current)
            levels = {
                row[0] for row in connection.execute("SELECT level FROM logs")
            }
            bodies = {
                row[0]
                for row in connection.execute(
                    "SELECT feedback_log_body FROM logs"
                )
            }
            connection.close()
            self.assertEqual(
                levels,
                {"TRACE", "DEBUG", "INFO", "WARN", "ERROR", "NOTICE"},
            )
            self.assertTrue(
                all(value.startswith("SYNTHETIC-") for value in bodies)
            )
            with self.assertRaises(ValueError):
                create_fixture(root)


if __name__ == "__main__":
    unittest.main()
