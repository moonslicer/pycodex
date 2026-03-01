"""Native sandbox command wrappers for shell execution."""

from __future__ import annotations

import shutil
import sys
from enum import StrEnum
from pathlib import Path


class SandboxPolicy(StrEnum):
    """Sandbox isolation level for command execution."""

    DANGER_FULL_ACCESS = "danger-full-access"
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"


class SandboxUnavailable(Exception):
    """Raised when restrictive sandboxing is requested but unavailable."""


def build_sandbox_argv(command: str, policy: SandboxPolicy, cwd: Path) -> list[str]:
    """Return subprocess argv for the requested sandbox policy."""
    if policy == SandboxPolicy.DANGER_FULL_ACCESS:
        return ["bash", "-c", command]

    adapter = _detect_native_sandbox()
    if adapter is None:
        raise SandboxUnavailable(
            f"No native sandbox available for policy {policy!r}; "
            "set --sandbox danger-full-access to proceed without isolation."
        )

    cwd_abs = cwd.resolve()
    if adapter == "sandbox-exec":
        return _build_sandbox_exec_argv(command=command, policy=policy, cwd=cwd_abs)
    if adapter == "firejail":
        return _build_firejail_argv(command=command, policy=policy, cwd=cwd_abs)
    if adapter == "bwrap":
        return _build_bwrap_argv(command=command, policy=policy, cwd=cwd_abs)

    raise SandboxUnavailable(f"Unsupported sandbox adapter {adapter!r} for policy {policy!r}.")


def _detect_native_sandbox() -> str | None:
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists():
        return "sandbox-exec"
    if sys.platform.startswith("linux"):
        if shutil.which("firejail") is not None:
            return "firejail"
        if shutil.which("bwrap") is not None:
            return "bwrap"
    return None


def _build_sandbox_exec_argv(*, command: str, policy: SandboxPolicy, cwd: Path) -> list[str]:
    profile = _sandbox_exec_profile(policy=policy, cwd=cwd)
    return ["/usr/bin/sandbox-exec", "-p", profile, "bash", "-c", command]


def _sandbox_exec_profile(*, policy: SandboxPolicy, cwd: Path) -> str:
    if policy == SandboxPolicy.READ_ONLY:
        return "(version 1) (allow default) (deny file-write*)"
    if policy == SandboxPolicy.WORKSPACE_WRITE:
        escaped = _seatbelt_escape(str(cwd))
        return (
            "(version 1) "
            "(allow default) "
            "(deny file-write*) "
            f'(allow file-write* (subpath "{escaped}"))'
        )
    raise ValueError(f"Unsupported policy for sandbox-exec profile: {policy!r}")


def _build_firejail_argv(*, command: str, policy: SandboxPolicy, cwd: Path) -> list[str]:
    base = ["firejail", "--quiet", "--read-only=/"]
    if policy == SandboxPolicy.WORKSPACE_WRITE:
        base.append(f"--read-write={cwd}")
    return [*base, "bash", "-c", command]


def _build_bwrap_argv(*, command: str, policy: SandboxPolicy, cwd: Path) -> list[str]:
    argv = [
        "bwrap",
        # --unshare-all additionally unshares the network namespace as a side effect.
        # Commands that require network access (curl, git clone, etc.) will fail with
        # a connection error rather than a file-write denial.  Dedicated network rules
        # are deferred to a later milestone.
        "--unshare-all",
        "--die-with-parent",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
    ]
    if policy == SandboxPolicy.WORKSPACE_WRITE:
        argv.extend(["--bind", str(cwd), str(cwd)])
    argv.extend(["--chdir", str(cwd), "bash", "-c", command])
    return argv


def _seatbelt_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
