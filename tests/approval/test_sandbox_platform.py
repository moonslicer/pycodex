from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from pycodex.approval.sandbox import SandboxPolicy, build_sandbox_argv


def _has_usable_macos_seatbelt() -> bool:
    if platform.system() != "Darwin":
        return False
    if not Path("/usr/bin/sandbox-exec").exists():
        return False
    try:
        result = subprocess.run(
            [
                "/usr/bin/sandbox-exec",
                "-p",
                "(version 1) (allow default)",
                "/usr/bin/true",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


_HAS_MACOS_SEATBELT = _has_usable_macos_seatbelt()
_HAS_LINUX_FIREJAIL = platform.system() == "Linux" and shutil.which("firejail") is not None


@pytest.mark.skipif(not _HAS_MACOS_SEATBELT, reason="requires macOS sandbox-exec")
def test_macos_seatbelt_read_only_blocks_write(tmp_path: Path) -> None:
    target = tmp_path / "blocked.txt"
    argv = build_sandbox_argv(
        f"touch {shlex.quote(str(target))}",
        SandboxPolicy.READ_ONLY,
        tmp_path,
    )

    result = subprocess.run(argv, cwd=tmp_path, check=False, capture_output=True, text=True)

    assert result.returncode != 0 or not target.exists()


@pytest.mark.skipif(not _HAS_MACOS_SEATBELT, reason="requires macOS sandbox-exec")
def test_macos_seatbelt_workspace_write_allows_cwd_write(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    argv = build_sandbox_argv(
        "printf 'hello' > out.txt",
        SandboxPolicy.WORKSPACE_WRITE,
        tmp_path,
    )

    result = subprocess.run(argv, cwd=tmp_path, check=False, capture_output=True, text=True)

    assert result.returncode == 0
    assert target.exists()


@pytest.mark.skipif(not _HAS_LINUX_FIREJAIL, reason="requires Linux firejail")
def test_linux_firejail_blocks_write(tmp_path: Path) -> None:
    target = tmp_path / "blocked.txt"
    argv = build_sandbox_argv(
        f"touch {shlex.quote(str(target))}",
        SandboxPolicy.READ_ONLY,
        tmp_path,
    )

    result = subprocess.run(argv, cwd=tmp_path, check=False, capture_output=True, text=True)

    assert result.returncode != 0 or not target.exists()
