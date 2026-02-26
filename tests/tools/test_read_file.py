from __future__ import annotations

import asyncio
from pathlib import Path

from pycodex.tools.read_file import ReadFileTool


def test_read_file_tool_reads_all_lines(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = asyncio.run(ReadFileTool().handle({"file_path": "sample.txt"}, tmp_path))

    assert result == "1: alpha\n2: beta\n3: gamma"


def test_read_file_tool_applies_offset_and_limit(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = asyncio.run(
        ReadFileTool().handle(
            {"file_path": "sample.txt", "offset": 1, "limit": 1},
            tmp_path,
        )
    )

    assert result == "2: beta"


def test_read_file_tool_missing_file_returns_error(tmp_path: Path) -> None:
    result = asyncio.run(ReadFileTool().handle({"file_path": "missing.txt"}, tmp_path))

    assert result == f"[ERROR] File not found: {tmp_path / 'missing.txt'}"


def test_read_file_tool_invalid_offset_returns_error(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = asyncio.run(ReadFileTool().handle({"file_path": "sample.txt", "offset": -1}, tmp_path))

    assert result == "[ERROR] Invalid arguments: 'offset' must be a non-negative integer"


def test_read_file_tool_invalid_limit_returns_error(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = asyncio.run(ReadFileTool().handle({"file_path": "sample.txt", "limit": 0}, tmp_path))

    assert result == "[ERROR] Invalid arguments: 'limit' must be a positive integer"
