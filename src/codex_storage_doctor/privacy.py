"""Privacy guardrails for public reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


# These keys represent raw values that must never enter an output report.
# Controlled finding prose uses ``detail`` rather than the historical logs
# column name ``message``.
FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "argv",
        "args",
        "body",
        "command",
        "command_line",
        "commandline",
        "environment",
        "feedback_log_body",
        "file",
        "message",
        "module",
        "module_path",
        "payload",
        "process_uuid",
        "target",
        "thread_id",
        "tool_input",
    }
)


class PrivacyViolation(ValueError):
    """Raised when a report contains a forbidden raw field."""


def assert_privacy_safe(value: Any, *, forbidden_values: Sequence[str] = ()) -> None:
    """Recursively reject raw log fields and known fixture canaries.

    This is a final serializer boundary, not a substitute for allowlisted SQL.
    """

    forbidden = tuple(item for item in forbidden_values if item)

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                normalized_key = str(key).strip().lower()
                if normalized_key in FORBIDDEN_OUTPUT_KEYS:
                    raise PrivacyViolation(f"forbidden output field: {normalized_key}")
                visit(child)
            return
        if isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            for child in item:
                visit(child)
            return
        if isinstance(item, str):
            for canary in forbidden:
                if canary in item:
                    raise PrivacyViolation("report contains a forbidden fixture canary")

    visit(value)


def controlled_error_code(error: BaseException) -> str:
    """Classify an exception without copying its potentially sensitive text."""

    name = type(error).__name__.lower()
    if "permission" in name:
        return "permission_denied"
    if "timeout" in name:
        return "timeout"
    return "operation_failed"
