"""Fail-closed native/local filesystem checks for mutation targets."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path, PureWindowsPath
import platform
import subprocess
from typing import Callable


REMOTE_FILESYSTEMS = frozenset(
    {
        "9p",
        "afs",
        "afpfs",
        "autofs",
        "ceph",
        "cifs",
        "davfs",
        "fuse.rclone",
        "fuse.sshfs",
        "glusterfs",
        "nfs",
        "nfs4",
        "osxfuse",
        "smb3",
        "smbfs",
        "sshfs",
        "webdav",
    }
)
LOCAL_FILESYSTEMS = frozenset(
    {
        "apfs",
        "btrfs",
        "devfs",
        "exfat",
        "ext2",
        "ext3",
        "ext4",
        "f2fs",
        "hfs",
        "hfsplus",
        "msdos",
        "ntfs",
        "ntfs3",
        "overlay",
        "tmpfs",
        "ufs",
        "vfat",
        "xfs",
        "zfs",
    }
)

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _default_runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(*args, **kwargs)  # type: ignore[arg-type]


def _decode_mount_path(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _linux_filesystem_type(path: Path, mountinfo_path: Path) -> str | None:
    try:
        lines = mountinfo_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return None
    target = path.resolve(strict=False)
    matches: list[tuple[int, str]] = []
    for line in lines:
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        fields = left.split()
        trailing = right.split()
        if len(fields) < 5 or not trailing:
            continue
        mount_point = Path(_decode_mount_path(fields[4]))
        try:
            target.relative_to(mount_point)
        except ValueError:
            continue
        matches.append((len(mount_point.parts), trailing[0].lower()))
    return max(matches, default=(0, ""))[1] or None


def _darwin_filesystem_type(path: Path, runner: Runner) -> str | None:
    try:
        result = runner(
            ["mount"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    target = path.resolve(strict=False)
    matches: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        prefix, separator, options = line.rpartition(" (")
        if not separator or not options.endswith(")"):
            continue
        _device, on_separator, mount_value = prefix.partition(" on ")
        if not on_separator:
            continue
        mount_point = Path(mount_value)
        try:
            target.relative_to(mount_point)
        except ValueError:
            continue
        filesystem = options[:-1].split(",", 1)[0].strip().lower()
        if filesystem:
            matches.append((len(mount_point.parts), filesystem))
    return max(matches, default=(0, ""))[1] or None


def _windows_root(path: Path) -> str | None:
    value = str(path)
    windows = PureWindowsPath(value)
    if value.startswith(("\\\\", "//")):
        parts = windows.parts
        if not parts:
            return None
        return str(windows.anchor or parts[0])
    if windows.drive:
        return f"{windows.drive}\\"
    return None


def _windows_drive_type(root: str) -> int | None:
    try:
        get_drive_type = ctypes.windll.kernel32.GetDriveTypeW  # type: ignore[attr-defined]
        get_drive_type.argtypes = [ctypes.c_wchar_p]
        get_drive_type.restype = ctypes.c_uint
        return int(get_drive_type(root))
    except (AttributeError, OSError):
        return None


def nonlocal_filesystem_reason(
    path: Path,
    *,
    platform_name: str | None = None,
    mountinfo_path: Path = Path("/proc/self/mountinfo"),
    runner: Runner | None = None,
    windows_drive_type: Callable[[str], int | None] | None = None,
) -> str | None:
    """Return a refusal reason, including when locality cannot be established."""

    system = (platform_name or platform.system()).lower()
    if system.startswith("linux"):
        filesystem = _linux_filesystem_type(path, mountinfo_path)
        if filesystem is None:
            return "filesystem locality could not be verified"
        if filesystem in REMOTE_FILESYSTEMS:
            return f"remote filesystem type {filesystem} is audit-only"
        if filesystem not in LOCAL_FILESYSTEMS:
            return f"filesystem type {filesystem} is not verified as local"
        return None
    if system.startswith(("darwin", "freebsd", "openbsd", "netbsd")):
        filesystem = _darwin_filesystem_type(
            path, _default_runner if runner is None else runner
        )
        if filesystem is None:
            return "filesystem locality could not be verified"
        if filesystem in REMOTE_FILESYSTEMS:
            return f"remote filesystem type {filesystem} is audit-only"
        if filesystem not in LOCAL_FILESYSTEMS:
            return f"filesystem type {filesystem} is not verified as local"
        return None
    if system.startswith("windows"):
        root = _windows_root(path)
        if root is None:
            return "Windows drive locality could not be verified"
        drive_type_fn = _windows_drive_type if windows_drive_type is None else windows_drive_type
        drive_type = drive_type_fn(root)
        if drive_type == 4:
            return "remote Windows drive is audit-only"
        if drive_type not in {2, 3, 6}:
            return "Windows drive locality could not be verified"
        return None
    return "filesystem locality is unsupported on this platform"
