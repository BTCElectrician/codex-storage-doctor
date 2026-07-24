#!/usr/bin/env python3
"""Create a disposable, synthetic-only Codex Storage Doctor demo fixture."""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import sys


SCHEMA = """
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    ts_nanos INTEGER NOT NULL,
    level TEXT NOT NULL,
    target TEXT NOT NULL,
    feedback_log_body TEXT,
    module_path TEXT,
    file TEXT,
    line INTEGER,
    thread_id TEXT,
    process_uuid TEXT,
    estimated_bytes INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_logs_ts ON logs(ts DESC, ts_nanos DESC, id DESC);
CREATE INDEX idx_logs_thread_id ON logs(thread_id);
CREATE INDEX idx_logs_process_uuid ON logs(process_uuid);
"""


def _create_database(path: Path, *, generation: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        for index, level in enumerate(
            ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "NOTICE"),
            start=1,
        ):
            connection.execute(
                """
                INSERT INTO logs (
                    ts, ts_nanos, level, target, feedback_log_body,
                    module_path, file, line, thread_id, process_uuid,
                    estimated_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generation,
                    index,
                    level,
                    "synthetic-target",
                    f"SYNTHETIC-PRIVATE-BODY-{generation}-{index}",
                    "synthetic::module",
                    "synthetic.rs",
                    index,
                    f"SYNTHETIC-THREAD-{generation}",
                    f"SYNTHETIC-PROCESS-{generation}",
                    100 + index,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def create_fixture(output: Path) -> tuple[Path, Path]:
    root = output.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("output directory must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    current_home = root / "current-codex-home"
    current = current_home / "logs_2.sqlite"
    stale = root / "stale-copy" / "logs_1.sqlite"
    _create_database(current, generation=2)
    _create_database(stale, generation=1)
    (current_home / "config.toml").write_text(
        'sqlite_home = "."\n',
        encoding="utf-8",
    )
    return current, stale


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create synthetic Codex log databases for a safe demo."
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        current, stale = create_fixture(args.output)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"fixture creation failed: {error}", file=sys.stderr)
        return 1
    print("Synthetic fixture created. It contains no real Codex data.")
    print(f"Current Codex home: {current.parent}")
    print(f"Explicit stale database: {stale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
