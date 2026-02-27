from __future__ import annotations

from pathlib import Path
from typing import Any

from pycodex.tools.base import ToolError, ToolResult
from pycodex.tools.list_dir import ListDirTool


def _expect_result(outcome: ToolResult | ToolError) -> ToolResult:
    assert isinstance(outcome, ToolResult)
    return outcome


def _expect_error(outcome: ToolResult | ToolError, *, code: str) -> ToolError:
    assert isinstance(outcome, ToolError)
    assert outcome.code == code
    return outcome


async def test_list_dir_tool_basic_listing_with_tree_indentation(tmp_path: Path) -> None:
    (tmp_path / "alpha.txt").write_text("x", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "child.txt").write_text("y", encoding="utf-8")

    result = await ListDirTool().handle({"dir_path": ".", "depth": 2}, tmp_path)
    body = _expect_result(result).body

    assert body == "alpha.txt\nnested/\n  child.txt"


async def test_list_dir_tool_respects_depth_limit(tmp_path: Path) -> None:
    deep = tmp_path / "level1" / "level2"
    deep.mkdir(parents=True)
    (deep / "leaf.txt").write_text("z", encoding="utf-8")

    result = await ListDirTool().handle({"dir_path": ".", "depth": 1}, tmp_path)
    body = _expect_result(result).body

    assert body == "level1/"


async def test_list_dir_tool_applies_offset_limit_and_more_entries_message(tmp_path: Path) -> None:
    for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")

    result = await ListDirTool().handle({"dir_path": ".", "offset": 2, "limit": 2}, tmp_path)
    body = _expect_result(result).body

    assert body == "b.txt\nc.txt\n\u2026 1 more entries"


async def test_list_dir_tool_marks_directories_and_symlinks(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    (tmp_path / "folder").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "file.txt")

    result = await ListDirTool().handle({"dir_path": ".", "depth": 1}, tmp_path)
    body = _expect_result(result).body

    assert "folder/" in body
    assert "link@" in body


async def test_list_dir_tool_nonexistent_path_returns_error(tmp_path: Path) -> None:
    result = await ListDirTool().handle({"dir_path": "missing"}, tmp_path)
    error = _expect_error(result, code="not_found")

    assert error.message == f"Directory not found: {tmp_path / 'missing'}"


async def test_list_dir_tool_rejects_path_outside_workspace(tmp_path: Path) -> None:
    result = await ListDirTool().handle({"dir_path": "../outside"}, tmp_path)
    assert isinstance(result, ToolError)
    assert result.code == "access_denied"


async def test_list_dir_tool_rejects_file_as_dir_path(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("content")
    result = await ListDirTool().handle({"dir_path": "file.txt"}, tmp_path)
    assert isinstance(result, ToolError)
    assert result.code == "not_a_directory"


async def test_list_dir_tool_rejects_offset_zero(tmp_path: Path) -> None:
    result = await ListDirTool().handle({"dir_path": ".", "offset": 0}, tmp_path)
    assert isinstance(result, ToolError)
    assert result.code == "invalid_arguments"


async def test_list_dir_tool_rejects_depth_over_max(tmp_path: Path) -> None:
    result = await ListDirTool().handle({"dir_path": ".", "depth": 11}, tmp_path)
    assert isinstance(result, ToolError)
    assert result.code == "invalid_arguments"


async def test_list_dir_tool_rejects_limit_over_max(tmp_path: Path) -> None:
    result = await ListDirTool().handle({"dir_path": ".", "limit": 2001}, tmp_path)
    assert isinstance(result, ToolError)
    assert result.code == "invalid_arguments"


async def test_list_dir_tool_offset_out_of_range(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    result = await ListDirTool().handle({"dir_path": ".", "offset": 100}, tmp_path)
    assert isinstance(result, ToolError)
    assert result.code == "offset_out_of_range"


async def test_list_dir_tool_offset_beyond_cap_returns_dedicated_error(
    tmp_path: Path, monkeypatch: Any
) -> None:
    # Simulate a capped traversal by lowering MAX_TOTAL_ENTRIES so that
    # offset lands past what was counted, triggering the offset_beyond_cap path.
    import pycodex.tools.list_dir as list_dir_mod

    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    (tmp_path / "c.txt").write_text("x")

    monkeypatch.setattr(list_dir_mod, "MAX_TOTAL_ENTRIES", 2)

    result = await ListDirTool().handle({"dir_path": ".", "offset": 10}, tmp_path)
    assert isinstance(result, ToolError)
    assert result.code == "offset_beyond_cap"
    assert "narrower path" in result.message
