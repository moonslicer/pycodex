"""Write-file tool handler."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from pycodex.tools.base import ToolError, ToolOutcome, ToolResult


class WriteFileTool:
    """Write text to a file path inside the current workspace."""

    name = "write_file"

    def tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Write text content to a file path in the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to write, relative to workspace or absolute.",
                        },
                        "content": {
                            "type": "string",
                            "description": "Text content to write to the target file.",
                        },
                    },
                    "required": ["file_path", "content"],
                    "additionalProperties": False,
                },
            },
        }

    async def is_mutating(self, args: dict[str, Any]) -> bool:
        _ = args
        return True

    def approval_key(self, args: dict[str, Any], cwd: Path) -> str | ToolError:
        """Return the approval cache key (resolved absolute path) for this call."""
        file_path = args.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolError(
                message="Invalid arguments: 'file_path' must be a non-empty string",
                code="invalid_arguments",
            )
        resolved = _resolve_path(file_path=file_path, cwd=cwd)
        if isinstance(resolved, ToolError):
            return resolved
        return str(resolved)

    async def handle(self, args: dict[str, Any], cwd: Path) -> ToolOutcome:
        file_path = args.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolError(
                message="Invalid arguments: 'file_path' must be a non-empty string",
                code="invalid_arguments",
            )

        content = args.get("content")
        if not isinstance(content, str):
            return ToolError(
                message="Invalid arguments: 'content' must be a string",
                code="invalid_arguments",
            )

        resolved_path = _resolve_path(file_path=file_path, cwd=cwd)
        if isinstance(resolved_path, ToolError):
            return resolved_path

        write_result = await asyncio.to_thread(_write_atomic, resolved_path, content)
        if isinstance(write_result, ToolError):
            return write_result

        return ToolResult(
            body={
                "path": str(resolved_path),
                "bytes_written": write_result,
            }
        )


def build_write_file_approval_key(args: dict[str, Any], cwd: Path) -> str | ToolError:
    """Return the approval cache key for write-file calls (thin wrapper for backwards compat)."""
    return WriteFileTool().approval_key(args, cwd)


def _resolve_path(*, file_path: str, cwd: Path) -> Path | ToolError:
    path = Path(file_path)
    if not path.is_absolute():
        path = cwd / path

    workspace_root = cwd.resolve()
    resolved_path = path.resolve(strict=False)
    if not resolved_path.is_relative_to(workspace_root):
        return ToolError(
            message=f"Access denied outside workspace: {resolved_path}",
            code="access_denied",
        )
    return resolved_path


def _write_atomic(path: Path, content: str) -> int | ToolError:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ToolError(message=f"Failed to create parent directories: {exc}", code="write_failed")

    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")

    try:
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, path)
    except OSError as exc:
        with suppress(OSError):
            temp_path.unlink(missing_ok=True)
        return ToolError(message=f"Failed to write file: {exc}", code="write_failed")

    return len(content.encode("utf-8"))
