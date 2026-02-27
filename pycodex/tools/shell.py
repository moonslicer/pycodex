"""Shell command tool handler."""

from __future__ import annotations

import asyncio
import re
import shlex
import time
from asyncio.subprocess import PIPE
from pathlib import Path
from typing import Any

from pycodex.tools.base import ToolError, ToolOutcome, ToolResult

DEFAULT_TIMEOUT_MS = 10_000
MAX_OUTPUT_BYTES = 1_048_576
_BASH_BINARIES = {"bash", "/bin/bash", "/usr/bin/bash"}
_SAFE_INLINE_TOKEN = re.compile(r"^[A-Za-z0-9._/:=,+-]+$")


class ShellTool:
    """Execute shell commands in the configured working directory."""

    name = "shell"

    def tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Run a shell command and return its output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute.",
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Optional command timeout in milliseconds.",
                        },
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            },
        }

    async def is_mutating(self, args: dict[str, Any]) -> bool:
        return True

    def approval_key(self, args: dict[str, Any], cwd: Path) -> dict[str, Any] | ToolError:
        """Return a deterministic approval key for shell commands.

        Equivalent wrapper forms such as `/bin/bash -lc "ls -la"` and
        `bash -lc "ls   -la"` normalize to the same key so session approvals
        remain stable across formatting differences.
        """
        _ = cwd
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolError(
                message="Invalid arguments: 'command' must be a non-empty string",
                code="invalid_arguments",
            )

        timeout_ms = _resolve_timeout_ms(args)
        if isinstance(timeout_ms, ToolError):
            return timeout_ms

        return {
            "tool": self.name,
            "command": _canonicalize_command_for_approval(command),
            "timeout_ms": timeout_ms,
        }

    async def handle(self, args: dict[str, Any], cwd: Path) -> ToolOutcome:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolError(
                message="Invalid arguments: 'command' must be a non-empty string",
                code="invalid_arguments",
            )

        timeout_ms = _resolve_timeout_ms(args)
        if isinstance(timeout_ms, ToolError):
            return timeout_ms

        started_at = time.perf_counter()
        try:
            process = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                command,
                cwd=cwd,
                stdout=PIPE,
                stderr=PIPE,
            )
        except OSError as exc:
            return ToolError(message=f"Failed to start command: {exc}", code="start_failed")

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_ms / 1000,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return ToolError(
                message=f"Command timed out after {timeout_ms}ms",
                code="timeout",
            )

        duration_seconds = round(time.perf_counter() - started_at, 1)
        output_text = _build_output_text(
            stdout_bytes=stdout_bytes,
            stderr_bytes=stderr_bytes,
        )
        payload = {
            "output": output_text,
            "metadata": {
                "exit_code": process.returncode,
                "duration_seconds": duration_seconds,
            },
        }
        return ToolResult(body=payload)


def _resolve_timeout_ms(args: dict[str, Any]) -> int | ToolError:
    timeout_ms = args.get("timeout_ms")
    if "timeout_seconds" in args:
        return ToolError(
            message="Invalid arguments: 'timeout_seconds' is unsupported; use 'timeout_ms'",
            code="invalid_arguments",
        )

    if timeout_ms is not None:
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms <= 0:
            return ToolError(
                message="Invalid arguments: 'timeout_ms' must be a positive integer",
                code="invalid_arguments",
            )
        return timeout_ms

    return DEFAULT_TIMEOUT_MS


def _build_output_text(*, stdout_bytes: bytes, stderr_bytes: bytes) -> str:
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")

    sections: list[str] = []
    if stdout_text:
        sections.append(f"stdout:\n{stdout_text}")
    if stderr_text:
        sections.append(f"stderr:\n{stderr_text}")
    if not sections:
        sections.append("(empty)")
    return _truncate_by_bytes("\n".join(sections))


def _canonicalize_command_for_approval(command: str) -> str:
    stripped = command.strip()
    parsed = _try_split_shell(stripped)
    if parsed is None:
        return stripped
    if len(parsed) != 3:
        return stripped

    executable, flag, inline_command = parsed
    if executable not in _BASH_BINARIES or flag != "-lc":
        return stripped

    canonical_inline = _normalize_safe_inline_whitespace(inline_command)
    return shlex.join(["bash", "-lc", canonical_inline])


def _normalize_safe_inline_whitespace(inline_command: str) -> str:
    compact = " ".join(inline_command.split())
    if not compact:
        return inline_command
    tokens = compact.split(" ")
    if all(_SAFE_INLINE_TOKEN.fullmatch(token) for token in tokens):
        return compact
    return inline_command


def _try_split_shell(command: str) -> list[str] | None:
    try:
        parsed = shlex.split(command, posix=True)
    except ValueError:
        return None
    if not parsed:
        return None
    return parsed


def _truncate_by_bytes(text: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return text

    truncated = encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore")
    return f"{truncated}\n...[truncated]"
