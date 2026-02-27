from __future__ import annotations

import json
from pathlib import Path

from pycodex.tools.shell import MAX_OUTPUT_BYTES, ShellTool


async def test_shell_tool_success(tmp_path: Path) -> None:
    result = await ShellTool().handle({"command": "echo hi"}, tmp_path)
    payload = json.loads(result)

    assert payload["metadata"]["exit_code"] == 0
    assert "stdout:\nhi\n" in payload["output"]


async def test_shell_tool_nonzero_exit(tmp_path: Path) -> None:
    result = await ShellTool().handle({"command": "echo nope 1>&2; exit 7"}, tmp_path)
    payload = json.loads(result)

    assert payload["metadata"]["exit_code"] == 7
    assert "stderr:\nnope\n" in payload["output"]


async def test_shell_tool_timeout_returns_error(tmp_path: Path) -> None:
    result = await ShellTool().handle(
        {"command": "python3 -c 'import time; time.sleep(0.2)'", "timeout_ms": 50},
        tmp_path,
    )

    assert result == "[ERROR] Command timed out after 50ms"


async def test_shell_tool_invalid_command_returns_error(tmp_path: Path) -> None:
    result = await ShellTool().handle({"command": ""}, tmp_path)

    assert result == "[ERROR] Invalid arguments: 'command' must be a non-empty string"


async def test_shell_tool_invalid_timeout_ms_returns_error(tmp_path: Path) -> None:
    result = await ShellTool().handle({"command": "echo hi", "timeout_ms": 0}, tmp_path)

    assert result == "[ERROR] Invalid arguments: 'timeout_ms' must be a positive integer"


async def test_shell_tool_timeout_seconds_is_rejected(tmp_path: Path) -> None:
    result = await ShellTool().handle({"command": "echo hi", "timeout_seconds": 1}, tmp_path)

    assert result == "[ERROR] Invalid arguments: 'timeout_seconds' is unsupported; use 'timeout_ms'"


async def test_shell_tool_truncates_large_output(tmp_path: Path) -> None:
    result = await ShellTool().handle(
        {"command": "python3 -c \"print('x' * 1100000)\""},
        tmp_path,
    )
    payload = json.loads(result)

    assert payload["metadata"]["exit_code"] == 0
    assert payload["output"].endswith("\n...[truncated]")
    assert len(payload["output"].encode("utf-8")) <= MAX_OUTPUT_BYTES + len(b"\n...[truncated]")
