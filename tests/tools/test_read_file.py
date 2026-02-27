from __future__ import annotations

from pathlib import Path
from typing import Any

from pycodex.tools.base import ToolError, ToolResult
from pycodex.tools.read_file import ReadFileTool


def _expect_result(outcome: ToolResult | ToolError) -> ToolResult:
    assert isinstance(outcome, ToolResult)
    return outcome


def _expect_error(outcome: ToolResult | ToolError, *, code: str) -> ToolError:
    assert isinstance(outcome, ToolError)
    assert outcome.code == code
    return outcome


def _parse_payload(result: ToolResult) -> dict[str, Any]:
    payload = result.body
    assert isinstance(payload, dict)
    assert isinstance(payload.get("output"), str)
    metadata = payload.get("metadata")
    assert isinstance(metadata, dict)
    return payload


async def test_read_file_tool_reads_all_lines(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = await ReadFileTool().handle({"file_path": "sample.txt", "limit": 10}, tmp_path)
    body = _expect_result(result).body
    assert body == "L1: alpha\nL2: beta\nL3: gamma"


async def test_read_file_tool_applies_offset_and_limit_in_json_mode(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = await ReadFileTool().handle(
        {
            "file_path": "sample.txt",
            "offset": 2,
            "limit": 1,
            "response_format": "json",
        },
        tmp_path,
    )
    payload = _parse_payload(_expect_result(result))

    assert payload["output"] == "L2: beta"
    assert payload["metadata"] == {
        "offset": 2,
        "limit": 1,
        "returned_lines": 1,
        "has_more": True,
        "next_offset": 3,
        "file_size_bytes": 17,
        "truncated": False,
    }


async def test_read_file_tool_missing_file_returns_error(tmp_path: Path) -> None:
    result = await ReadFileTool().handle({"file_path": "missing.txt"}, tmp_path)
    error = _expect_error(result, code="not_found")

    assert error.message == f"File not found: {tmp_path / 'missing.txt'}"


async def test_read_file_tool_invalid_offset_returns_error(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = await ReadFileTool().handle({"file_path": "sample.txt", "offset": 0}, tmp_path)
    error = _expect_error(result, code="invalid_arguments")

    assert error.message == "Invalid arguments: 'offset' must be a positive integer (1-indexed)"


async def test_read_file_tool_invalid_limit_returns_error(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = await ReadFileTool().handle({"file_path": "sample.txt", "limit": 0}, tmp_path)
    error = _expect_error(result, code="invalid_arguments")

    assert error.message == "Invalid arguments: 'limit' must be a positive integer"


async def test_read_file_tool_applies_default_limit(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    lines = [f"line-{index}" for index in range(1, 301)]
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = await ReadFileTool().handle(
        {"file_path": "sample.txt", "response_format": "json"}, tmp_path
    )
    payload = _parse_payload(_expect_result(result))

    assert payload["output"].splitlines()[0] == "L1: line-1"
    assert payload["output"].splitlines()[-1] == "L200: line-200"
    assert payload["metadata"] == {
        "offset": 1,
        "limit": 200,
        "returned_lines": 200,
        "has_more": True,
        "next_offset": 201,
        "file_size_bytes": file_path.stat().st_size,
        "truncated": False,
    }


async def test_read_file_tool_rejects_limit_over_max(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = await ReadFileTool().handle({"file_path": "sample.txt", "limit": 2001}, tmp_path)
    error = _expect_error(result, code="invalid_arguments")

    assert error.message == "Invalid arguments: 'limit' must be <= 2000"


async def test_read_file_tool_offset_exceeds_file_length(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = await ReadFileTool().handle(
        {"file_path": "sample.txt", "offset": 10, "limit": 1}, tmp_path
    )
    error = _expect_error(result, code="offset_out_of_range")

    assert error.message == "offset exceeds file length"


async def test_read_file_tool_handles_non_utf8_content(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(b"\xff\xfe\nplain\n")

    result = await ReadFileTool().handle(
        {"file_path": "sample.bin", "limit": 2, "response_format": "json"},
        tmp_path,
    )
    payload = _parse_payload(_expect_result(result))

    assert payload["output"] == "L1: \ufffd\ufffd\nL2: plain"


async def test_read_file_tool_truncates_long_line(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text(f"{'x' * 600}\n", encoding="utf-8")

    result = await ReadFileTool().handle(
        {"file_path": "sample.txt", "limit": 1, "response_format": "json"},
        tmp_path,
    )
    payload = _parse_payload(_expect_result(result))

    line = payload["output"]
    assert isinstance(line, str)
    assert line.startswith("L1: " + ("x" * 500))
    assert line.endswith("...[truncated]")


async def test_read_file_tool_rejects_path_outside_workspace(tmp_path: Path) -> None:
    result = await ReadFileTool().handle({"file_path": "../outside.txt", "limit": 1}, tmp_path)
    error = _expect_error(result, code="access_denied")

    assert error.message.startswith("Access denied outside workspace: ")


async def test_read_file_tool_empty_file_offset_exceeds_file_length(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.txt"
    file_path.write_text("", encoding="utf-8")

    result = await ReadFileTool().handle({"file_path": "empty.txt", "offset": 2}, tmp_path)
    error = _expect_error(result, code="offset_out_of_range")

    assert error.message == "offset exceeds file length"


async def test_read_file_tool_empty_file_text_mode_returns_empty_marker(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.txt"
    file_path.write_text("", encoding="utf-8")

    result = await ReadFileTool().handle({"file_path": "empty.txt"}, tmp_path)
    body = _expect_result(result).body

    assert body == "(empty file)"


async def test_read_file_tool_invalid_response_format_returns_error(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = await ReadFileTool().handle(
        {"file_path": "sample.txt", "response_format": "yaml"}, tmp_path
    )
    error = _expect_error(result, code="invalid_arguments")

    assert error.message == "Invalid arguments: 'response_format' must be 'text' or 'json'"
