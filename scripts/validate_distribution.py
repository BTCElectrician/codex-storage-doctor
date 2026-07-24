#!/usr/bin/env python3
"""Validate the local package, skill, plugin, and marketplace boundaries."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-storage-doctor"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
SKILL = PLUGIN / "skills" / "codex-storage-doctor" / "SKILL.md"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    try:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
        require(
            project["project"]["name"] == "codex-storage-doctor",
            "wrong project name",
        )
        require(project["project"]["dependencies"] == [], "runtime deps must be empty")
        require((ROOT / "scripts" / "build_wheel.py").is_file(), "wheel builder missing")
        require(
            (ROOT / "scripts" / "verify_artifacts.py").is_file(),
            "artifact verifier missing",
        )
        require(
            (ROOT / "scripts" / "run_tests.py").is_file(),
            "isolated test runner missing",
        )

        manifest = json.loads(MANIFEST.read_text("utf-8"))
        require(manifest["name"] == PLUGIN.name, "plugin name/folder mismatch")
        require(re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"]) is not None, "bad semver")
        require(manifest["skills"] == "./skills/", "bad skill path")
        require(
            list((PLUGIN / ".codex-plugin").iterdir()) == [MANIFEST],
            "only plugin.json may live in .codex-plugin",
        )

        skill = SKILL.read_text("utf-8")
        require(skill.startswith("---\n"), "skill frontmatter missing")
        require("name: codex-storage-doctor" in skill, "skill name missing")
        require("description:" in skill.split("---", 2)[1], "skill description missing")
        require("TODO" not in skill, "skill contains TODO")
        require(len(skill.splitlines()) < 500, "skill exceeds 500 lines")

        marketplace = json.loads(MARKETPLACE.read_text("utf-8"))
        entries = marketplace["plugins"]
        require(len(entries) == 1, "marketplace must contain one plugin")
        entry = entries[0]
        require(entry["name"] == manifest["name"], "marketplace name mismatch")
        source = entry["source"]["path"]
        require(source.startswith("./"), "marketplace path must start ./")
        require((ROOT / source[2:]).resolve() == PLUGIN.resolve(), "marketplace path mismatch")
        require(entry["policy"]["installation"] == "AVAILABLE", "bad install policy")
        require(entry["policy"]["authentication"] == "ON_INSTALL", "bad auth policy")
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"distribution validation failed: {error}", file=sys.stderr)
        return 1
    print("distribution validation: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
