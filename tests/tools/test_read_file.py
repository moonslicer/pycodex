from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pycodex.tools.read_file import ReadFileTool


def _parse_payload(result: str) -> dict[str, object]:
    payload = json.loads(result)
    assert isinstance(payload, dict)
    assert isinstance(payload.get("output"), str)
    metadata = payload.get("metadata")
    assert isinstance(metadata, dict)
    return payload


def test_read_file_tool_reads_all_lines(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = asyncio.run(ReadFileTool().handle({"file_path": "sample.txt", "limit": 10}, tmp_path))
    assert result == "L1: alpha\nL2: beta\nL3: gamma"


def test_read_file_tool_applies_offset_and_limit_in_json_mode(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = asyncio.run(
        ReadFileTool().handle(
            {
                "file_path": "sample.txt",
                "offset": 2,
                "limit": 1,
                "response_format": "json",
            },
            tmp_path,
        )
    )
    payload = _parse_payload(result)

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


def test_read_file_tool_missing_file_returns_error(tmp_path: Path) -> None:
    result = asyncio.run(ReadFileTool().handle({"file_path": "missing.txt"}, tmp_path))

    assert result == f"[ERROR] File not found: {tmp_path / 'missing.txt'}"


def test_read_file_tool_invalid_offset_returns_error(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = asyncio.run(ReadFileTool().handle({"file_path": "sample.txt", "offset": 0}, tmp_path))

    assert result == "[ERROR] Invalid arguments: 'offset' must be a positive integer (1-indexed)"


def test_read_file_tool_invalid_limit_returns_error(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = asyncio.run(ReadFileTool().handle({"file_path": "sample.txt", "limit": 0}, tmp_path))

    assert result == "[ERROR] Invalid arguments: 'limit' must be a positive integer"


def test_read_file_tool_applies_default_limit(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    lines = [f"line-{index}" for index in range(1, 301)]
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = asyncio.run(
        ReadFileTool().handle({"file_path": "sample.txt", "response_format": "json"}, tmp_path)
    )
    payload = _parse_payload(result)

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


def test_read_file_tool_rejects_limit_over_max(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = asyncio.run(
        ReadFileTool().handle({"file_path": "sample.txt", "limit": 2001}, tmp_path)
    )

    assert result == "[ERROR] Invalid arguments: 'limit' must be <= 2000"


def test_read_file_tool_offset_exceeds_file_length(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = asyncio.run(
        ReadFileTool().handle({"file_path": "sample.txt", "offset": 10, "limit": 1}, tmp_path)
    )

    assert result == "[ERROR] offset exceeds file length"


def test_read_file_tool_handles_non_utf8_content(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(b"\xff\xfe\nplain\n")

    result = asyncio.run(
        ReadFileTool().handle(
            {"file_path": "sample.bin", "limit": 2, "response_format": "json"},
            tmp_path,
        )
    )
    payload = _parse_payload(result)

    assert payload["output"] == "L1: \ufffd\ufffd\nL2: plain"


def test_read_file_tool_truncates_long_line(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text(f"{'x' * 600}\n", encoding="utf-8")

    result = asyncio.run(
        ReadFileTool().handle(
            {"file_path": "sample.txt", "limit": 1, "response_format": "json"},
            tmp_path,
        )
    )
    payload = _parse_payload(result)

    line = payload["output"]
    assert isinstance(line, str)
    assert line.startswith("L1: " + ("x" * 500))
    assert line.endswith("...[truncated]")


def test_read_file_tool_rejects_path_outside_workspace(tmp_path: Path) -> None:
    result = asyncio.run(
        ReadFileTool().handle({"file_path": "../outside.txt", "limit": 1}, tmp_path)
    )

    assert result.startswith("[ERROR] Access denied outside workspace: ")


def test_read_file_tool_empty_file_offset_exceeds_file_length(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.txt"
    file_path.write_text("", encoding="utf-8")

    result = asyncio.run(ReadFileTool().handle({"file_path": "empty.txt", "offset": 2}, tmp_path))

    assert result == "[ERROR] offset exceeds file length"


def test_read_file_tool_empty_file_text_mode_returns_empty_marker(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.txt"
    file_path.write_text("", encoding="utf-8")

    result = asyncio.run(ReadFileTool().handle({"file_path": "empty.txt"}, tmp_path))

    assert result == "(empty file)"


def test_read_file_tool_invalid_response_format_returns_error(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = asyncio.run(
        ReadFileTool().handle({"file_path": "sample.txt", "response_format": "yaml"}, tmp_path)
    )

    assert result == "[ERROR] Invalid arguments: 'response_format' must be 'text' or 'json'"
