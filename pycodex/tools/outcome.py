"""Shared typed outcomes for tool handlers and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias


@dataclass(slots=True, frozen=True)
class ToolResult:
    """Structured successful tool output."""

    body: Any


@dataclass(slots=True, frozen=True)
class ToolError:
    """Structured tool failure payload."""

    message: str
    code: str | None = None


ToolOutcome: TypeAlias = ToolResult | ToolError
