"""Read-file tool handler."""

from __future__ import annotations

from pathlib import Path
from typing import Any


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
                            "minimum": 0,
                            "description": "Optional 0-based starting line offset.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Optional maximum number of lines to return.",
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

        offset = args.get("offset", 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            return "[ERROR] Invalid arguments: 'offset' must be a non-negative integer"

        limit = args.get("limit")
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0
        ):
            return "[ERROR] Invalid arguments: 'limit' must be a positive integer"

        path = Path(file_path)
        if not path.is_absolute():
            path = cwd / path

        if not path.exists():
            return f"[ERROR] File not found: {path}"
        if not path.is_file():
            return f"[ERROR] Not a file: {path}"

        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"[ERROR] Failed to read file: {exc}"

        lines = content.splitlines()
        if not lines:
            return "(empty file)"

        numbered_lines = list(enumerate(lines, start=1))
        end = None if limit is None else offset + limit
        window = numbered_lines[offset:end]
        if not window:
            return "(no lines in requested range)"

        return "\n".join(f"{line_no}: {line}" for line_no, line in window)
