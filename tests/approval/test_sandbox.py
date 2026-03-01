from __future__ import annotations

from pathlib import Path

import pytest
from pycodex.approval.sandbox import (
    SandboxPolicy,
    SandboxUnavailable,
    build_sandbox_argv,
)


def test_danger_full_access_returns_bare_argv(tmp_path: Path) -> None:
    assert build_sandbox_argv("ls", SandboxPolicy.DANGER_FULL_ACCESS, tmp_path) == [
        "bash",
        "-c",
        "ls",
    ]


def test_sandbox_policy_enum_values() -> None:
    assert SandboxPolicy.DANGER_FULL_ACCESS.value == "danger-full-access"
    assert SandboxPolicy.READ_ONLY.value == "read-only"
    assert SandboxPolicy.WORKSPACE_WRITE.value == "workspace-write"


def test_sandbox_unavailable_is_exception() -> None:
    assert issubclass(SandboxUnavailable, Exception)


def test_restrictive_policy_raises_when_no_sandbox_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("pycodex.approval.sandbox._detect_native_sandbox", lambda: None)

    with pytest.raises(SandboxUnavailable):
        build_sandbox_argv("ls", SandboxPolicy.READ_ONLY, tmp_path)


def test_restrictive_policy_wraps_when_sandbox_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "pycodex.approval.sandbox._detect_native_sandbox",
        lambda: "sandbox-exec",
    )

    argv = build_sandbox_argv("ls", SandboxPolicy.READ_ONLY, tmp_path)

    assert argv
    assert argv != ["bash", "-c", "ls"]
