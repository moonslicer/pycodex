"""Directory-listing tool handler."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pycodex.tools.base import ToolError, ToolOutcome, ToolResult

DEFAULT_OFFSET = 1
DEFAULT_LIMIT = 25
DEFAULT_DEPTH = 2
MAX_LIMIT = 2_000
MAX_DEPTH = 10
MAX_ENTRY_CHARS = 500
MAX_TOTAL_ENTRIES = 50_000


class ListDirTool:
    """List workspace directory contents with tree indentation and paging."""

    name = "list_dir"

    def tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "List directory entries with optional pagination and depth limit.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dir_path": {
                            "type": "string",
                            "description": "Directory path to list.",
                        },
                        "offset": {
                            "type": "integer",
                            "minimum": 1,
                            "description": f"Optional 1-indexed offset. Defaults to {DEFAULT_OFFSET}.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 2000,
                            "description": (
                                "Optional entry count to return. "
                                f"Defaults to {DEFAULT_LIMIT}, max {MAX_LIMIT}."
                            ),
                        },
                        "depth": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                            "description": (
                                "Optional maximum depth. "
                                f"Defaults to {DEFAULT_DEPTH}, max {MAX_DEPTH}."
                            ),
                        },
                    },
                    "required": ["dir_path"],
                    "additionalProperties": False,
                },
            },
        }

    async def is_mutating(self, args: dict[str, Any]) -> bool:
        return False

    async def handle(self, args: dict[str, Any], cwd: Path) -> ToolOutcome:
        dir_path = args.get("dir_path")
        if not isinstance(dir_path, str) or not dir_path.strip():
            return ToolError(
                message="Invalid arguments: 'dir_path' must be a non-empty string",
                code="invalid_arguments",
            )

        offset = _read_positive_int(args, key="offset", default=DEFAULT_OFFSET)
        if isinstance(offset, ToolError):
            return offset

        limit = _read_positive_int(args, key="limit", default=DEFAULT_LIMIT)
        if isinstance(limit, ToolError):
            return limit
        if limit > MAX_LIMIT:
            return ToolError(
                message=f"Invalid arguments: 'limit' must be <= {MAX_LIMIT}",
                code="invalid_arguments",
            )

        depth = _read_positive_int(args, key="depth", default=DEFAULT_DEPTH)
        if isinstance(depth, ToolError):
            return depth
        if depth > MAX_DEPTH:
            return ToolError(
                message=f"Invalid arguments: 'depth' must be <= {MAX_DEPTH}",
                code="invalid_arguments",
            )

        collected = await asyncio.to_thread(
            _prepare_and_collect,
            dir_path,
            cwd,
            depth,
            offset,
            limit,
        )
        if isinstance(collected, ToolError):
            return collected
        window, total_entries, capped = collected

        if total_entries == 0:
            if offset != DEFAULT_OFFSET:
                return ToolError(
                    message="offset exceeds directory entry count", code="offset_out_of_range"
                )
            return ToolResult(body="(empty directory)")

        start_index = offset - 1
        if not window:
            if capped:
                return ToolError(
                    message=(
                        f"offset exceeds enumerated entries: directory has "
                        f"{MAX_TOTAL_ENTRIES}+ entries. Use a narrower path or smaller depth."
                    ),
                    code="offset_beyond_cap",
                )
            return ToolError(
                message="offset exceeds directory entry count", code="offset_out_of_range"
            )

        remaining = total_entries - (start_index + len(window))
        rendered = "\n".join(window)
        if remaining > 0:
            if capped:
                rendered = f"{rendered}\n\u2026 {MAX_TOTAL_ENTRIES}+ entries"
            else:
                rendered = f"{rendered}\n\u2026 {remaining} more entries"

        return ToolResult(body=rendered)


def _read_positive_int(args: dict[str, Any], *, key: str, default: int) -> int | ToolError:
    value = args.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return ToolError(
            message=f"Invalid arguments: '{key}' must be a positive integer",
            code="invalid_arguments",
        )
    return value


def _prepare_directory(dir_path: str, cwd: Path) -> Path | ToolError:
    candidate = Path(dir_path)
    if not candidate.is_absolute():
        candidate = cwd / candidate

    workspace_root = cwd.resolve()
    resolved_path = candidate.resolve(strict=False)
    if not resolved_path.is_relative_to(workspace_root):
        return ToolError(
            message=f"Access denied outside workspace: {resolved_path}",
            code="access_denied",
        )
    if not resolved_path.exists():
        return ToolError(message=f"Directory not found: {resolved_path}", code="not_found")
    if not resolved_path.is_dir():
        return ToolError(message=f"Not a directory: {resolved_path}", code="not_a_directory")
    return resolved_path


def _prepare_and_collect(
    dir_path: str,
    cwd: Path,
    depth: int,
    offset: int,
    limit: int,
) -> tuple[list[str], int, bool] | ToolError:
    """Prepare the directory path then collect the listing window and total count.

    Returns a tuple of (window, total_entries, capped) where capped indicates
    that the traversal hit MAX_TOTAL_ENTRIES and stopped early.
    """
    prepared = _prepare_directory(dir_path, cwd)
    if isinstance(prepared, ToolError):
        return prepared
    return _collect_window_and_count(prepared, depth, offset, limit)


def _collect_window_and_count(
    root: Path,
    depth: int,
    offset: int,
    limit: int,
) -> tuple[list[str], int, bool] | ToolError:
    window: list[str] = []
    start_index = offset - 1
    end_index = start_index + limit
    total_entries = 0
    capped = False

    def walk(current: Path, level: int) -> None:
        nonlocal total_entries, capped
        children = sorted(current.iterdir(), key=lambda item: item.name)
        for child in children:
            if total_entries >= MAX_TOTAL_ENTRIES:
                capped = True
                return
            marker = _entry_marker(child)
            label = _truncate_entry(f"{child.name}{marker}")
            if start_index <= total_entries < end_index:
                window.append(f"{'  ' * level}{label}")
            total_entries += 1

            if level + 1 >= depth:
                continue
            # Do not recurse into symlinked directories to avoid infinite cycles
            if child.is_symlink() or not child.is_dir():
                continue

            walk(child, level + 1)

    try:
        walk(root, 0)
    except OSError as exc:
        return ToolError(message=f"Failed to list directory: {exc}", code="read_failed")

    return window, total_entries, capped


def _entry_marker(path: Path) -> str:
    if path.is_symlink():
        return "@"
    if path.is_dir():
        return "/"
    return ""


def _truncate_entry(value: str) -> str:
    if len(value) <= MAX_ENTRY_CHARS:
        return value
    return f"{value[:MAX_ENTRY_CHARS]}...[truncated]"
