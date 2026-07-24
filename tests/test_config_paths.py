from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_storage_doctor.config import ConfigReadError, load_config_sqlite_homes
from codex_storage_doctor.paths import (
    _wsl_windows_home,
    classify_candidate_activity,
    discover_candidates,
    is_cross_boundary_path,
)


def touch_database(root: Path, name: str = "logs_2.sqlite") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_bytes(b"synthetic")
    return path


class ConfigAndPathTests(unittest.TestCase):
    def test_config_parsing_is_narrow_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.toml"
            config.write_text(
                """
profile = "zeta"
sqlite_home = "top"
unrelated_secret = "DO-NOT-RETURN"

[profiles.zeta]
sqlite_home = "zeta"
other = "PRIVATE"

[profiles.alpha]
sqlite_home = "alpha"
""",
                encoding="utf-8",
            )
            homes = load_config_sqlite_homes(config)
            self.assertEqual(
                [home.source for home in homes],
                [
                    "config:top_level",
                    "config:profile:alpha",
                    "config:profile:zeta",
                ],
            )
            self.assertEqual(homes[0].path, root / "top")
            self.assertFalse(homes[1].selected_profile)
            self.assertTrue(homes[2].selected_profile)
            self.assertNotIn("DO-NOT-RETURN", repr(homes))
            self.assertNotIn("PRIVATE", repr(homes))

    def test_invalid_config_has_controlled_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.toml"
            config.write_text("private = 'CANARY'\ninvalid = [", encoding="utf-8")
            with self.assertRaisesRegex(ConfigReadError, "parsed safely") as caught:
                load_config_sqlite_homes(config)
            self.assertNotIn("CANARY", str(caught.exception))

    def test_discovery_precedence_deduplication_and_profile_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            explicit_sqlite = root / "explicit-sqlite"
            explicit_codex = root / "explicit-codex"
            env_sqlite = root / "env-sqlite"
            env_codex = root / "env-codex"
            configured_top = home / ".codex" / "configured-top"
            configured_alpha = home / ".codex" / "configured-alpha"
            configured_zeta = home / ".codex" / "configured-zeta"
            default = home / ".codex"

            expected_paths = [
                touch_database(explicit_sqlite),
                touch_database(env_sqlite),
                touch_database(explicit_codex),
                touch_database(env_codex),
                touch_database(configured_top),
                touch_database(configured_alpha),
                touch_database(configured_zeta),
                touch_database(default),
            ]
            default.joinpath("config.toml").write_text(
                """
profile = "zeta"
sqlite_home = "configured-top"
[profiles.zeta]
sqlite_home = "configured-zeta"
[profiles.alpha]
sqlite_home = "configured-alpha"
""",
                encoding="utf-8",
            )

            candidates = discover_candidates(
                explicit_codex_homes=(explicit_codex,),
                explicit_sqlite_homes=(explicit_sqlite, env_sqlite),
                environ={
                    "CODEX_SQLITE_HOME": str(env_sqlite),
                    "CODEX_HOME": str(env_codex),
                },
                home=home,
                platform_name="linux",
            )

            self.assertEqual([item.path for item in candidates], expected_paths)
            self.assertEqual(
                [item.report_id for item in candidates],
                [f"database-{index:03d}" for index in range(1, 9)],
            )
            self.assertEqual(
                candidates[1].sources,
                ("explicit:sqlite_home", "environment:CODEX_SQLITE_HOME"),
            )
            self.assertIn("explicit_selection", candidates[0].evidence_labels)
            self.assertIn("configured_profile", candidates[4].evidence_labels)
            self.assertIn("configured_profile", candidates[5].evidence_labels)
            self.assertIn("configured_profile", candidates[6].evidence_labels)
            self.assertIn("configured_current", candidates[1].evidence_labels)
            self.assertNotIn("configured_current", candidates[3].evidence_labels)
            rendered = json.dumps([item.to_dict() for item in candidates])
            self.assertNotIn(str(root), rendered)

    def test_known_filename_precedes_other_log_databases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            touch_database(root, "logs_9.sqlite")
            touch_database(root, "logs_2.sqlite")
            candidates = discover_candidates(
                explicit_sqlite_homes=(root,),
                environ={},
                home=root / "unused-home",
                platform_name="linux",
            )
            self.assertEqual(
                [candidate.path.name for candidate in candidates],
                ["logs_2.sqlite", "logs_9.sqlite"],
            )
            self.assertTrue(candidates[0].known_filename)
            self.assertFalse(candidates[1].known_filename)

    def test_cross_boundary_paths_are_classified_without_disk_access(self) -> None:
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "paths.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(
            is_cross_boundary_path(
                fixture["windows"][1],
                platform_name="win32",
                environ={},
            )
        )
        self.assertTrue(
            is_cross_boundary_path(
                fixture["wsl"][1],
                platform_name="linux",
                environ={"WSL_DISTRO_NAME": "Ubuntu"},
            )
        )
        self.assertFalse(
            is_cross_boundary_path(
                "/mnt/c/Users/user/.codex/logs_2.sqlite",
                platform_name="linux",
                environ={},
            )
        )

    def test_native_windows_default_and_wsl_windows_home_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_home = root / "windows-user"
            native_database = touch_database(native_home / ".codex")
            native = discover_candidates(
                environ={},
                home=native_home,
                platform_name="win32",
            )
            self.assertEqual([candidate.path for candidate in native], [native_database])
            self.assertIn("configured_current", native[0].evidence_labels)

            wsl_windows_home = root / "mounted-windows-user"
            wsl_database = touch_database(wsl_windows_home / ".codex")
            mapped_home = _wsl_windows_home(
                {"USERPROFILE": r"C:\Users\synthetic"}
            )
            self.assertIsNotNone(mapped_home)
            assert mapped_home is not None
            self.assertEqual(
                mapped_home.as_posix(),
                "/mnt/c/Users/synthetic",
            )
            with patch(
                "codex_storage_doctor.paths._wsl_windows_home",
                return_value=wsl_windows_home,
            ):
                wsl = discover_candidates(
                    environ={
                        "WSL_DISTRO_NAME": "Ubuntu",
                        "USERPROFILE": r"C:\Users\synthetic",
                    },
                    home=root / "linux-user",
                    platform_name="linux",
                )
            self.assertEqual([candidate.path for candidate in wsl], [wsl_database])
            self.assertEqual(
                wsl[0].sources,
                ("platform:wsl_windows_default",),
            )
            self.assertFalse(wsl[0].mutation_allowed)

    def test_selected_profile_wins_current_label_over_top_level(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            codex_home = home / ".codex"
            top = touch_database(codex_home / "top")
            selected = touch_database(codex_home / "selected")
            codex_home.joinpath("config.toml").write_text(
                """
profile = "selected"
sqlite_home = "top"
[profiles.selected]
sqlite_home = "selected"
""",
                encoding="utf-8",
            )
            candidates = discover_candidates(
                environ={},
                home=home,
                platform_name="linux",
            )
            by_path = {candidate.path: candidate for candidate in candidates}
            self.assertNotIn("configured_current", by_path[top].evidence_labels)
            self.assertIn("configured_profile", by_path[top].evidence_labels)
            self.assertIn("configured_current", by_path[selected].evidence_labels)

    def test_stale_duplicate_requires_older_mtime_than_direct_activity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = touch_database(root / "active")
            older = touch_database(root / "older")
            newer = touch_database(root / "newer")
            os.utime(older, ns=(1_000, 1_000))
            os.utime(active, ns=(2_000, 2_000))
            os.utime(newer, ns=(3_000, 3_000))
            candidates = discover_candidates(
                explicit_sqlite_homes=(active, older, newer),
                environ={},
                home=root / "unused",
                platform_name="linux",
            )
            classified = classify_candidate_activity(
                candidates,
                changed_paths=(active,),
            )
            by_path = {candidate.path: candidate for candidate in classified}
            self.assertIn("changed_during_sample", by_path[active].evidence_labels)
            self.assertIn("stale_duplicate", by_path[older].evidence_labels)
            self.assertNotIn("stale_duplicate", by_path[newer].evidence_labels)


if __name__ == "__main__":
    unittest.main()
