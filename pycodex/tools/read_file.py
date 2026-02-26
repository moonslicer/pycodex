"""Read-file tool handler."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

DEFAULT_LIMIT = 200
MAX_LIMIT = 2_000
MAX_LINE_CHARS = 500
MAX_OUTPUT_BYTES = 262_144
MAX_PARALLEL_READS = 4

_READ_SEMAPHORE = asyncio.Semaphore(MAX_PARALLEL_READS)


class ReadFileTool:
    """Read file content and render it with line numbers."""

    name = "read_file"

    def tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Read a text file with optional line slicing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to the file to read.",
                        },
                        "offset": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Optional 1-indexed starting line number.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "description": (
                                "Optional maximum number of lines to return. "
                                f"Defaults to {DEFAULT_LIMIT}, max {MAX_LIMIT}."
                            ),
                        },
                        "response_format": {
                            "type": "string",
                            "enum": ["text", "json"],
                            "description": (
                                "Optional output format. "
                                "'text' (default) returns line content only; "
                                "'json' returns output plus paging metadata."
                            ),
                        },
                    },
                    "required": ["file_path"],
                    "additionalProperties": False,
                },
            },
        }

    async def is_mutating(self, args: dict[str, Any]) -> bool:
        _ = args
        return False

    async def handle(self, args: dict[str, Any], cwd: Path) -> str:
        file_path = args.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            return "[ERROR] Invalid arguments: 'file_path' must be a non-empty string"

        offset = args.get("offset", 1)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset <= 0:
            return "[ERROR] Invalid arguments: 'offset' must be a positive integer (1-indexed)"

        raw_limit = args.get("limit")
        if raw_limit is not None and (
            not isinstance(raw_limit, int) or isinstance(raw_limit, bool) or raw_limit <= 0
        ):
            return "[ERROR] Invalid arguments: 'limit' must be a positive integer"
        limit = DEFAULT_LIMIT if raw_limit is None else raw_limit
        if limit > MAX_LIMIT:
            return f"[ERROR] Invalid arguments: 'limit' must be <= {MAX_LIMIT}"

        response_format = args.get("response_format", "text")
        if response_format not in {"text", "json"}:
            return "[ERROR] Invalid arguments: 'response_format' must be 'text' or 'json'"

        prepared = await asyncio.to_thread(_resolve_path_and_size, file_path, cwd)
        if isinstance(prepared, str):
            return prepared
        path, file_size_bytes = prepared

        async with _READ_SEMAPHORE:
            try:
                window, total_seen, has_more = await asyncio.to_thread(
                    _read_window,
                    path,
                    offset,
                    limit,
                )
            except OSError as exc:
                return f"[ERROR] Failed to read file: {exc}"

        if total_seen == 0:
            if offset > 1:
                return "[ERROR] offset exceeds file length"
            if response_format == "text":
                return "(empty file)"
            return json.dumps(
                {
                    "output": "(empty file)",
                    "metadata": {
                        "offset": offset,
                        "limit": limit,
                        "returned_lines": 0,
                        "has_more": False,
                        "next_offset": None,
                        "file_size_bytes": file_size_bytes,
                        "truncated": False,
                    },
                },
                ensure_ascii=True,
            )

        if offset > total_seen and not window:
            return "[ERROR] offset exceeds file length"

        output_text, truncated = _format_window(window)
        if response_format == "text":
            return output_text

        payload = {
            "output": output_text,
            "metadata": {
                "offset": offset,
                "limit": limit,
                "returned_lines": len(window),
                "has_more": has_more,
                "next_offset": (offset + len(window)) if has_more else None,
                "file_size_bytes": file_size_bytes,
                "truncated": truncated,
            },
        }
        return json.dumps(payload, ensure_ascii=True)


def _read_window(path: Path, offset: int, limit: int) -> tuple[list[tuple[int, str]], int, bool]:
    window: list[tuple[int, str]] = []
    total_seen = 0
    has_more = False
    start = offset - 1

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            total_seen += 1
            zero_index = total_seen - 1
            if zero_index < start:
                continue
            if len(window) >= limit:
                has_more = True
                break

            normalized = raw_line.rstrip("\n")
            if normalized.endswith("\r"):
                normalized = normalized[:-1]
            window.append((total_seen, _truncate_line(normalized)))

    return window, total_seen, has_more


def _resolve_path_and_size(file_path: str, cwd: Path) -> tuple[Path, int] | str:
    path = Path(file_path)
    if not path.is_absolute():
        path = cwd / path

    cwd_root = cwd.resolve()
    resolved_path = path.resolve(strict=False)
    if not resolved_path.is_relative_to(cwd_root):
        return f"[ERROR] Access denied outside workspace: {resolved_path}"

    if not resolved_path.exists():
        return f"[ERROR] File not found: {resolved_path}"
    if not resolved_path.is_file():
        return f"[ERROR] Not a file: {resolved_path}"

    try:
        file_size_bytes = resolved_path.stat().st_size
    except OSError as exc:
        return f"[ERROR] Failed to read file: {exc}"

    return resolved_path, file_size_bytes


def _truncate_line(line: str) -> str:
    if len(line) <= MAX_LINE_CHARS:
        return line
    return f"{line[:MAX_LINE_CHARS]}...[truncated]"


def _format_window(window: list[tuple[int, str]]) -> tuple[str, bool]:
    if not window:
        return "(no lines in requested range)", False

    rendered = "\n".join(f"L{line_no}: {line}" for line_no, line in window)
    encoded = rendered.encode("utf-8")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return rendered, False

    truncated = encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore")
    return f"{truncated}\n...[truncated]", True
