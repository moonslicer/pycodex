"""Shell command tool handler."""

from __future__ import annotations

import asyncio
import json
import time
from asyncio.subprocess import PIPE
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_MS = 10_000
MAX_OUTPUT_BYTES = 1_048_576


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
        _ = args
        return True

    async def handle(self, args: dict[str, Any], cwd: Path) -> str:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return "[ERROR] Invalid arguments: 'command' must be a non-empty string"

        timeout_ms = _resolve_timeout_ms(args)
        if isinstance(timeout_ms, str):
            return timeout_ms

        started_at = time.perf_counter()
        try:
            process = await asyncio.create_subprocess_exec(
                "bash",
                "-lc",
                command,
                cwd=str(cwd),
                stdout=PIPE,
                stderr=PIPE,
            )
        except OSError as exc:
            return f"[ERROR] Failed to start command: {exc}"

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_ms / 1000,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return f"[ERROR] Command timed out after {timeout_ms}ms"

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
        return json.dumps(payload, ensure_ascii=True)


def _resolve_timeout_ms(args: dict[str, Any]) -> int | str:
    timeout_ms = args.get("timeout_ms")
    if "timeout_seconds" in args:
        return "[ERROR] Invalid arguments: 'timeout_seconds' is unsupported; use 'timeout_ms'"

    if timeout_ms is not None:
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms <= 0:
            return "[ERROR] Invalid arguments: 'timeout_ms' must be a positive integer"
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


def _truncate_by_bytes(text: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return text

    truncated = encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore")
    return f"{truncated}\n...[truncated]"
