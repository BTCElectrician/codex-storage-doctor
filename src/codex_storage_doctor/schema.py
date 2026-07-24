"""Supported Codex diagnostic-log schema boundary."""

from __future__ import annotations


REQUIRED_LOG_COLUMNS = frozenset(
    {
        "id",
        "ts",
        "ts_nanos",
        "level",
        "target",
        "module_path",
        "file",
        "line",
        "thread_id",
        "process_uuid",
        "estimated_bytes",
    }
)
BODY_COLUMNS = frozenset({"message", "feedback_log_body"})
