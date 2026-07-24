from __future__ import annotations

import sqlite3
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def create_database(root: Path, schema: str = "logs_v2.sql") -> Path:
    path = root / "logs_2.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript((FIXTURES / schema).read_text(encoding="utf-8"))
    connection.commit()
    connection.close()
    return path


def clear_process_scan(*args, **kwargs):
    return {
        "complete": True,
        "status": "complete",
        "processes": [],
        "open_database_paths": [],
        "errors": [],
    }


def active_process_scan(*args, **kwargs):
    return {
        "complete": True,
        "status": "complete",
        "processes": [{"pid": 123, "surface": "cli", "executable": "codex"}],
        "open_database_paths": [],
        "errors": [],
    }


def partial_process_scan(*args, **kwargs):
    return {
        "complete": False,
        "status": "partial",
        "processes": [],
        "open_database_paths": [],
        "errors": ["synthetic adapter unavailable"],
    }
