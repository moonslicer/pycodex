"""Content-search tool handler."""

from __future__ import annotations

import asyncio
import shutil
from asyncio.subprocess import PIPE
from pathlib import Path
from typing import Any

from pycodex.tools.base import ToolError, ToolOutcome, ToolResult

DEFAULT_LIMIT = 100
MAX_LIMIT = 2_000
TIMEOUT_MS = 30_000


class GrepFilesTool:
    """Search file contents and return matching file paths."""

    name = "grep_files"

    def tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Find files containing a pattern under a workspace path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Regular expression pattern to search for.",
                        },
                        "path": {
                            "type": "string",
                            "description": "Optional file or directory path to search under.",
                        },
                        "include": {
                            "type": "string",
                            "description": "Optional glob include filter, for example '*.py'.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "description": (
                                f"Optional match limit. Defaults to {DEFAULT_LIMIT}, max {MAX_LIMIT}."
                            ),
                        },
                    },
                    "required": ["pattern"],
                    "additionalProperties": False,
                },
            },
        }

    async def is_mutating(self, args: dict[str, Any]) -> bool:
        _ = args
        return False

    async def handle(self, args: dict[str, Any], cwd: Path) -> ToolOutcome:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            return ToolError(
                message="Invalid arguments: 'pattern' must be a non-empty string",
                code="invalid_arguments",
            )

        include = args.get("include")
        if include is not None and (not isinstance(include, str) or not include.strip()):
            return ToolError(
                message="Invalid arguments: 'include' must be a non-empty string",
                code="invalid_arguments",
            )

        raw_limit = args.get("limit", DEFAULT_LIMIT)
        if not isinstance(raw_limit, int) or isinstance(raw_limit, bool) or raw_limit <= 0:
            return ToolError(
                message="Invalid arguments: 'limit' must be a positive integer",
                code="invalid_arguments",
            )
        if raw_limit > MAX_LIMIT:
            return ToolError(
                message=f"Invalid arguments: 'limit' must be <= {MAX_LIMIT}",
                code="invalid_arguments",
            )

        workspace_root = await asyncio.to_thread(cwd.resolve)
        target = await asyncio.to_thread(
            _resolve_target_path, args.get("path"), cwd, workspace_root
        )
        if isinstance(target, ToolError):
            return target

        use_rg = shutil.which("rg") is not None
        raw_matches = await _run_search(
            use_rg=use_rg,
            pattern=pattern,
            include=include,
            target=target,
            workspace_root=workspace_root,
        )
        if isinstance(raw_matches, ToolError):
            return raw_matches

        sorted_matches = await asyncio.to_thread(_sort_by_mtime, raw_matches, workspace_root)
        truncated = len(sorted_matches) > raw_limit

        return ToolResult(
            body={
                "matches": sorted_matches[:raw_limit],
                "truncated": truncated,
            }
        )


def _resolve_target_path(path_arg: Any, cwd: Path, workspace_root: Path) -> Path | ToolError:
    if path_arg is None:
        candidate = cwd
    elif isinstance(path_arg, str) and path_arg.strip():
        candidate = Path(path_arg)
        if not candidate.is_absolute():
            candidate = cwd / candidate
    else:
        return ToolError(
            message="Invalid arguments: 'path' must be a non-empty string when provided",
            code="invalid_arguments",
        )

    resolved_path = candidate.resolve(strict=False)
    if not resolved_path.is_relative_to(workspace_root):
        return ToolError(
            message=f"Access denied outside workspace: {resolved_path}",
            code="access_denied",
        )
    if not resolved_path.exists():
        return ToolError(message=f"Path not found: {resolved_path}", code="not_found")

    return resolved_path


async def _run_search(
    *,
    use_rg: bool,
    pattern: str,
    include: str | None,
    target: Path,
    workspace_root: Path,
) -> list[str] | ToolError:
    relative_target = str(target.relative_to(workspace_root))
    if relative_target == ".":
        relative_target = "."

    if use_rg:
        command = [
            "rg",
            "--files-with-matches",
            "--sortr=modified",
            "--regexp",
            pattern,
        ]
        if include is not None:
            command.extend(["--glob", include])
        command.extend(["--", relative_target])
        return await _exec_search_command(command=command, cwd=workspace_root)

    command = ["grep", "-rl", pattern]
    if include is not None:
        command.extend(["--include", include])
    command.append(relative_target)
    return await _exec_search_command(command=command, cwd=workspace_root)


async def _exec_search_command(command: list[str], cwd: Path) -> list[str] | ToolError:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=PIPE,
            stderr=PIPE,
        )
    except OSError as exc:
        return ToolError(message=f"Failed to start search command: {exc}", code="start_failed")

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=TIMEOUT_MS / 1_000,
        )
    except TimeoutError:
        process.kill()
        await process.communicate()
        return ToolError(message=f"Command timed out after {TIMEOUT_MS}ms", code="timeout")

    if process.returncode == 1:
        return []
    if process.returncode != 0:
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        message = f"Search command failed with exit code {process.returncode}"
        if stderr_text:
            message = f"{message}: {stderr_text}"
        return ToolError(message=message, code="command_failed")

    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    return _normalize_lines(stdout_text.splitlines())


def _normalize_lines(lines: list[str]) -> list[str]:
    matches: list[str] = []
    seen: set[str] = set()
    for line in lines:
        candidate = line.strip()
        if not candidate:
            continue

        normalized = Path(candidate).as_posix()
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized in seen:
            continue

        seen.add(normalized)
        matches.append(normalized)
    return matches


def _sort_by_mtime(paths: list[str], workspace_root: Path) -> list[str]:
    def key(path_text: str) -> float:
        target = (workspace_root / path_text).resolve(strict=False)
        try:
            return target.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(paths, key=key, reverse=True)
