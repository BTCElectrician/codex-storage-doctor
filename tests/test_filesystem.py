from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from helpers import create_database
from codex_storage_doctor.filesystem import nonlocal_filesystem_reason
from codex_storage_doctor.planning import SafetyBoundaryError, create_plan


class FilesystemBoundaryTests(unittest.TestCase):
    def test_linux_mountinfo_distinguishes_local_and_remote(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "logs_2.sqlite"
            target.touch()
            resolved_root = root.resolve()
            mountinfo = root / "mountinfo"
            mountinfo.write_text(
                f"36 25 0:32 / {resolved_root} rw - ext4 /dev/synthetic rw\n",
                encoding="utf-8",
            )
            self.assertIsNone(
                nonlocal_filesystem_reason(
                    target,
                    platform_name="linux",
                    mountinfo_path=mountinfo,
                )
            )
            mountinfo.write_text(
                f"36 25 0:32 / {resolved_root} rw - nfs server:/share rw\n",
                encoding="utf-8",
            )
            self.assertIn(
                "remote filesystem",
                nonlocal_filesystem_reason(
                    target,
                    platform_name="linux",
                    mountinfo_path=mountinfo,
                )
                or "",
            )

    def test_darwin_mount_output_and_windows_drive_type_fail_closed(self) -> None:
        def remote_mount(*_args, **_kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout="server:/share on /Volumes/Remote (smbfs, nodev)\n",
            )

        self.assertIn(
            "remote filesystem",
            nonlocal_filesystem_reason(
                Path("/Volumes/Remote/logs_2.sqlite"),
                platform_name="darwin",
                runner=remote_mount,
            )
            or "",
        )

        def unknown_mount(*_args, **_kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout="synthetic on /Volumes/Unknown (mysteryfs, local)\n",
            )

        self.assertIn(
            "not verified as local",
            nonlocal_filesystem_reason(
                Path("/Volumes/Unknown/logs_2.sqlite"),
                platform_name="darwin",
                runner=unknown_mount,
            )
            or "",
        )
        self.assertIn(
            "remote Windows drive",
            nonlocal_filesystem_reason(
                Path(r"Z:\Codex\logs_2.sqlite"),
                platform_name="windows",
                windows_drive_type=lambda _root: 4,
            )
            or "",
        )
        self.assertIn(
            "could not be verified",
            nonlocal_filesystem_reason(
                Path(r"C:\Codex\logs_2.sqlite"),
                platform_name="windows",
                windows_drive_type=lambda _root: None,
            )
            or "",
        )

    def test_plan_refuses_nonlocal_filesystem_before_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_database(Path(directory))
            with (
                patch(
                    "codex_storage_doctor.planning.nonlocal_filesystem_reason",
                    return_value="remote filesystem type nfs is audit-only",
                ),
                self.assertRaisesRegex(SafetyBoundaryError, "audit-only"),
            ):
                create_plan(database, "balanced")


if __name__ == "__main__":
    unittest.main()
