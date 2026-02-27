from __future__ import annotations

import asyncio
from pathlib import Path

from pycodex.tools.base import ToolError, ToolResult
from pycodex.tools.write_file import WriteFileTool


def _expect_result(outcome: ToolResult | ToolError) -> ToolResult:
    assert isinstance(outcome, ToolResult)
    return outcome


def _expect_error(outcome: ToolResult | ToolError, *, code: str) -> ToolError:
    assert isinstance(outcome, ToolError)
    assert outcome.code == code
    return outcome


async def test_write_file_tool_writes_content_and_reports_bytes(tmp_path: Path) -> None:
    result = await WriteFileTool().handle(
        {"file_path": "hello.txt", "content": "hello world"},
        tmp_path,
    )
    payload = _expect_result(result).body

    assert payload == {
        "path": str(tmp_path / "hello.txt"),
        "bytes_written": len(b"hello world"),
    }
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello world"


async def test_write_file_tool_uses_atomic_tmp_path_and_cleans_it_up(tmp_path: Path) -> None:
    result = await WriteFileTool().handle(
        {"file_path": "notes.txt", "content": "abc"},
        tmp_path,
    )
    _expect_result(result)

    # Temp file uses .{name}.{pid}.tmp pattern — none should remain after success
    remaining_tmps = await asyncio.to_thread(lambda: list(tmp_path.glob(".notes.txt.*.tmp")))
    assert remaining_tmps == [], f"Unexpected temp files: {remaining_tmps}"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "abc"


async def test_write_file_tool_rejects_path_outside_workspace(tmp_path: Path) -> None:
    result = await WriteFileTool().handle(
        {"file_path": "../outside.txt", "content": "nope"},
        tmp_path,
    )
    error = _expect_error(result, code="access_denied")

    assert error.message.startswith("Access denied outside workspace: ")


async def test_write_file_tool_creates_missing_parent_directories(tmp_path: Path) -> None:
    result = await WriteFileTool().handle(
        {"file_path": "a/b/c/file.txt", "content": "created"},
        tmp_path,
    )
    _expect_result(result)

    assert (tmp_path / "a" / "b" / "c" / "file.txt").read_text(encoding="utf-8") == "created"


async def test_write_file_tool_overwrites_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "overwrite.txt"
    target.write_text("old", encoding="utf-8")

    result = await WriteFileTool().handle(
        {"file_path": "overwrite.txt", "content": "new value"},
        tmp_path,
    )
    _expect_result(result)

    assert target.read_text(encoding="utf-8") == "new value"


def test_approval_key_returns_resolved_absolute_path(tmp_path: Path) -> None:
    key = WriteFileTool().approval_key({"file_path": "foo.txt"}, tmp_path)
    assert key == str(tmp_path / "foo.txt")


def test_approval_key_rejects_whitespace_file_path(tmp_path: Path) -> None:
    result = WriteFileTool().approval_key({"file_path": "   "}, tmp_path)
    assert isinstance(result, ToolError)
    assert result.code == "invalid_arguments"


def test_approval_key_rejects_missing_file_path(tmp_path: Path) -> None:
    result = WriteFileTool().approval_key({}, tmp_path)
    assert isinstance(result, ToolError)
    assert result.code == "invalid_arguments"


async def test_write_file_tool_rejects_missing_content(tmp_path: Path) -> None:
    result = await WriteFileTool().handle({"file_path": "x.txt"}, tmp_path)
    assert isinstance(result, ToolError)
    assert result.code == "invalid_arguments"


async def test_write_file_tool_rejects_non_string_content(tmp_path: Path) -> None:
    result = await WriteFileTool().handle({"file_path": "x.txt", "content": 42}, tmp_path)
    assert isinstance(result, ToolError)
    assert result.code == "invalid_arguments"


async def test_write_file_tool_reports_unicode_byte_count(tmp_path: Path) -> None:
    content = "こんにちは"  # 5 chars, 15 UTF-8 bytes
    result = await WriteFileTool().handle(
        {"file_path": "unicode.txt", "content": content}, tmp_path
    )
    payload = _expect_result(result).body
    assert payload["bytes_written"] == 15
