"""Shell command tool handler."""

from __future__ import annotations

import asyncio
from asyncio.subprocess import PIPE
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 8_000


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
                        "timeout_seconds": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 600,
                            "description": "Optional command timeout in seconds.",
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

        timeout_seconds = args.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            return "[ERROR] Invalid arguments: 'timeout_seconds' must be a positive integer"

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
                timeout=timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return f"[ERROR] Command timed out after {timeout_seconds}s"

        stdout_text = _truncate(stdout_bytes.decode("utf-8", errors="replace"))
        stderr_text = _truncate(stderr_bytes.decode("utf-8", errors="replace"))

        sections = [f"exit_code: {process.returncode}"]
        if stdout_text:
            sections.append(f"stdout:\n{stdout_text}")
        if stderr_text:
            sections.append(f"stderr:\n{stderr_text}")
        if not stdout_text and not stderr_text:
            sections.append("output: (empty)")
        return "\n".join(sections)


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return f"{text[:MAX_OUTPUT_CHARS]}\n...[truncated]"
