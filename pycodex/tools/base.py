"""Core tool contracts and routing primitives."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class ToolHandler(Protocol):
    """Protocol implemented by all tool handlers."""

    name: str

    def tool_spec(self) -> dict[str, Any]:
        """Return the OpenAI-compatible tool specification."""

    async def is_mutating(self, args: dict[str, Any]) -> bool:
        """Return whether this call mutates state."""

    async def handle(self, args: dict[str, Any], cwd: Path) -> str:
        """Execute tool logic and return string result."""


class ToolRegistry:
    """In-memory registry for tool handlers."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolHandler] = {}

    def register(self, handler: ToolHandler) -> None:
        """Register or replace a tool handler by name."""
        self._tools[handler.name] = handler

    def get(self, name: str) -> ToolHandler | None:
        """Look up a registered handler by name."""
        return self._tools.get(name)

    def tool_specs(self) -> list[dict[str, Any]]:
        """Return tool specs for all registered handlers."""
        return [handler.tool_spec() for handler in self._tools.values()]

    async def dispatch(self, name: str, args: dict[str, Any], cwd: Path) -> str:
        """Dispatch a tool call by name and return tool output text."""
        handler = self.get(name)
        if handler is None:
            return f"[ERROR] Unknown tool: {name}"

        try:
            return await handler.handle(args, cwd)
        except Exception as exc:  # pragma: no cover - defensive boundary
            return f"[ERROR] Tool '{name}' failed ({type(exc).__name__})"


@dataclass(slots=True)
class RoutedToolCall:
    """Normalized tool call input from model responses."""

    name: str
    call_id: str
    arguments: dict[str, Any]


class ToolRouter:
    """Route model tool calls to registered handlers."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def tool_specs(self) -> list[dict[str, Any]]:
        """Expose registered tool specs for model API payloads."""
        return self._registry.tool_specs()

    async def dispatch(
        self,
        *,
        name: str,
        arguments: str | dict[str, Any],
        cwd: Path,
    ) -> str:
        """Dispatch a tool call payload from the model."""
        parsed_args = self._parse_arguments(arguments)
        if isinstance(parsed_args, str):
            return parsed_args
        return await self._registry.dispatch(name=name, args=parsed_args, cwd=cwd)

    @staticmethod
    def _parse_arguments(arguments: str | dict[str, Any]) -> dict[str, Any] | str:
        if isinstance(arguments, dict):
            return arguments

        try:
            decoded = json.loads(arguments)
        except json.JSONDecodeError as exc:
            return f"[ERROR] Invalid tool arguments JSON: {exc.msg}"

        if not isinstance(decoded, dict):
            return "[ERROR] Invalid tool arguments JSON: expected object"

        return decoded
