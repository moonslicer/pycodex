from __future__ import annotations

from pathlib import Path

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
