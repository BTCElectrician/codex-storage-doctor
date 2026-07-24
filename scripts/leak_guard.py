#!/usr/bin/env python3
"""Fail if repository content looks like private logs, secrets, or local state."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "build", "dist", "work", "outputs", "__pycache__"}
SKIP_SUFFIXES = {
    ".pyc",
    ".sqlite",
    ".db",
    ".wal",
    ".shm",
    ".backup",
    ".whl",
    ".pyz",
}
FORBIDDEN = {
    "private user home": re.compile(r"/Users/collin(?:/|\\b)", re.IGNORECASE),
    "private Windows home": re.compile(
        r"[A-Z]:\\\\Users\\\\collin(?:\\\\|\\b)", re.IGNORECASE
    ),
    "OpenAI key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "Anthropic key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "Codex session path": re.compile(r"\.codex/sessions/\d{4}/\d{2}/\d{2}/"),
}


def files() -> list[Path]:
    result: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        result.append(path)
    return sorted(result)


def main() -> int:
    problems: list[str] = []
    for path in files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{path.relative_to(ROOT)}: unexpected binary file")
            continue
        for label, pattern in FORBIDDEN.items():
            if pattern.search(text):
                problems.append(f"{path.relative_to(ROOT)}: {label}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"leak guard: ok ({len(files())} text files scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
