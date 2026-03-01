from __future__ import annotations

from asyncio.subprocess import PIPE
from pathlib import Path

import pytest
from pycodex.approval.sandbox import SandboxPolicy, SandboxUnavailable
from pycodex.tools.base import ToolError, ToolResult
from pycodex.tools.shell import MAX_OUTPUT_BYTES, ShellTool


def _approval_key_for(command: str, cwd: Path) -> dict[str, object]:
    key = ShellTool().approval_key({"command": command}, cwd)
    assert isinstance(key, dict)
    return key


async def test_shell_tool_success(tmp_path: Path) -> None:
    result = await ShellTool().handle({"command": "echo hi"}, tmp_path)
    assert isinstance(result, ToolResult)

    payload = result.body
    assert isinstance(payload, dict)
    assert payload["metadata"]["exit_code"] == 0
    assert "stdout:\nhi\n" in payload["output"]


async def test_shell_tool_nonzero_exit(tmp_path: Path) -> None:
    result = await ShellTool().handle({"command": "echo nope 1>&2; exit 7"}, tmp_path)
    assert isinstance(result, ToolResult)

    payload = result.body
    assert isinstance(payload, dict)
    assert payload["metadata"]["exit_code"] == 7
    assert "stderr:\nnope\n" in payload["output"]


async def test_shell_tool_timeout_returns_error(tmp_path: Path) -> None:
    result = await ShellTool().handle(
        {"command": "python3 -c 'import time; time.sleep(0.2)'", "timeout_ms": 50},
        tmp_path,
    )

    assert result == ToolError(message="Command timed out after 50ms", code="timeout")


async def test_shell_tool_invalid_command_returns_error(tmp_path: Path) -> None:
    result = await ShellTool().handle({"command": ""}, tmp_path)

    assert result == ToolError(
        message="Invalid arguments: 'command' must be a non-empty string",
        code="invalid_arguments",
    )


async def test_shell_tool_invalid_timeout_ms_returns_error(tmp_path: Path) -> None:
    result = await ShellTool().handle({"command": "echo hi", "timeout_ms": 0}, tmp_path)

    assert result == ToolError(
        message="Invalid arguments: 'timeout_ms' must be a positive integer",
        code="invalid_arguments",
    )


async def test_shell_tool_timeout_seconds_is_rejected(tmp_path: Path) -> None:
    result = await ShellTool().handle({"command": "echo hi", "timeout_seconds": 1}, tmp_path)

    assert result == ToolError(
        message="Invalid arguments: 'timeout_seconds' is unsupported; use 'timeout_ms'",
        code="invalid_arguments",
    )


async def test_shell_tool_truncates_large_output(tmp_path: Path) -> None:
    result = await ShellTool().handle(
        {"command": "python3 -c \"print('x' * 1100000)\""},
        tmp_path,
    )
    assert isinstance(result, ToolResult)

    payload = result.body
    assert isinstance(payload, dict)
    assert payload["metadata"]["exit_code"] == 0
    assert payload["output"].endswith("\n...[truncated]")
    assert len(payload["output"].encode("utf-8")) <= MAX_OUTPUT_BYTES + len(b"\n...[truncated]")


def test_shell_approval_key_normalizes_wrapper_and_safe_inline_whitespace(tmp_path: Path) -> None:
    first = _approval_key_for('bash -lc "ls -la"', tmp_path)
    second = _approval_key_for('/bin/bash -lc "ls   -la"', tmp_path)
    assert first == second


def test_shell_approval_key_preserves_semantically_sensitive_inline_forms(tmp_path: Path) -> None:
    unquoted = _approval_key_for('bash -lc "echo $HOME"', tmp_path)
    single_quoted = _approval_key_for("bash -lc \"echo '$HOME'\"", tmp_path)
    escaped = _approval_key_for('bash -lc "echo \\$HOME"', tmp_path)
    assert unquoted != single_quoted
    assert unquoted != escaped


def test_canonical_command_returns_normalized_string() -> None:
    command = ShellTool().canonical_command({"command": '/bin/bash -lc "ls   -la"'})
    assert command == "bash -lc 'ls -la'"


def test_canonical_command_returns_none_on_missing_command() -> None:
    command = ShellTool().canonical_command({})
    assert command is None


async def test_sandbox_execute_danger_full_access_matches_handle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seen: dict[str, object] = {}

    class _FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (b"ok\n", b"")

    async def fake_create_subprocess_exec(
        *argv: str,
        cwd: Path,
        stdout: int,
        stderr: int,
    ) -> _FakeProcess:
        seen["argv"] = list(argv)
        seen["cwd"] = cwd
        seen["stdout"] = stdout
        seen["stderr"] = stderr
        return _FakeProcess()

    monkeypatch.setattr(
        "pycodex.tools.shell.asyncio.create_subprocess_exec", fake_create_subprocess_exec
    )

    outcome = await ShellTool().sandbox_execute(
        {"command": "echo hi"},
        tmp_path,
        SandboxPolicy.DANGER_FULL_ACCESS,
    )

    assert isinstance(outcome, ToolResult)
    assert seen["argv"] == ["bash", "-c", "echo hi"]
    assert seen["cwd"] == tmp_path
    assert seen["stdout"] == PIPE
    assert seen["stderr"] == PIPE


async def test_sandbox_execute_propagates_sandbox_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_build_sandbox_argv(*, command: str, policy: SandboxPolicy, cwd: Path) -> list[str]:
        _ = command, policy, cwd
        raise SandboxUnavailable("missing sandbox")

    monkeypatch.setattr("pycodex.tools.shell.build_sandbox_argv", fail_build_sandbox_argv)

    with pytest.raises(SandboxUnavailable, match="missing sandbox"):
        await ShellTool().sandbox_execute(
            {"command": "echo hi"},
            tmp_path,
            SandboxPolicy.READ_ONLY,
        )


async def test_sandbox_execute_nonzero_exit_matches_handle_behavior(tmp_path: Path) -> None:
    result = await ShellTool().sandbox_execute(
        {"command": "echo nope 1>&2; exit 7"},
        tmp_path,
        SandboxPolicy.DANGER_FULL_ACCESS,
    )
    assert isinstance(result, ToolResult)

    payload = result.body
    assert isinstance(payload, dict)
    assert payload["metadata"]["exit_code"] == 7
    assert "stderr:\nnope\n" in payload["output"]


async def test_sandbox_execute_timeout_returns_error(tmp_path: Path) -> None:
    result = await ShellTool().sandbox_execute(
        {"command": "python3 -c 'import time; time.sleep(0.2)'", "timeout_ms": 50},
        tmp_path,
        SandboxPolicy.DANGER_FULL_ACCESS,
    )

    assert result == ToolError(message="Command timed out after 50ms", code="timeout")


async def test_sandbox_execute_truncates_large_output(tmp_path: Path) -> None:
    result = await ShellTool().sandbox_execute(
        {"command": "python3 -c \"print('x' * 1100000)\""},
        tmp_path,
        SandboxPolicy.DANGER_FULL_ACCESS,
    )
    assert isinstance(result, ToolResult)

    payload = result.body
    assert isinstance(payload, dict)
    assert payload["metadata"]["exit_code"] == 0
    assert payload["output"].endswith("\n...[truncated]")
    assert len(payload["output"].encode("utf-8")) <= MAX_OUTPUT_BYTES + len(b"\n...[truncated]")
