from __future__ import annotations

import asyncio
from pathlib import Path

from pycodex.tools.shell import ShellTool


def test_shell_tool_success(tmp_path: Path) -> None:
    result = asyncio.run(ShellTool().handle({"command": "echo hi"}, tmp_path))

    assert "exit_code: 0" in result
    assert "stdout:\nhi\n" in result


def test_shell_tool_nonzero_exit(tmp_path: Path) -> None:
    result = asyncio.run(ShellTool().handle({"command": "echo nope 1>&2; exit 7"}, tmp_path))

    assert "exit_code: 7" in result
    assert "stderr:\nnope\n" in result


def test_shell_tool_timeout_returns_error(tmp_path: Path) -> None:
    result = asyncio.run(ShellTool().handle({"command": "sleep 2", "timeout_seconds": 1}, tmp_path))

    assert result == "[ERROR] Command timed out after 1s"


def test_shell_tool_invalid_command_returns_error(tmp_path: Path) -> None:
    result = asyncio.run(ShellTool().handle({"command": ""}, tmp_path))

    assert result == "[ERROR] Invalid arguments: 'command' must be a non-empty string"


def test_shell_tool_invalid_timeout_returns_error(tmp_path: Path) -> None:
    result = asyncio.run(ShellTool().handle({"command": "echo hi", "timeout_seconds": 0}, tmp_path))

    assert result == "[ERROR] Invalid arguments: 'timeout_seconds' must be a positive integer"
