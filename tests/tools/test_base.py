from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pycodex.tools.base import ToolRegistry, ToolRouter


class _FakeTool:
    name = "fake"

    def tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "fake tool",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }

    async def is_mutating(self, args: dict[str, Any]) -> bool:
        _ = args
        return False

    async def handle(self, args: dict[str, Any], cwd: Path) -> str:
        return f"ok:{cwd}:{args.get('x', '')}"


class _BoomTool(_FakeTool):
    name = "boom"

    async def handle(self, args: dict[str, Any], cwd: Path) -> str:
        _ = args, cwd
        raise RuntimeError("explode")


def test_registry_starts_empty() -> None:
    registry = ToolRegistry()
    assert registry.tool_specs() == []


def test_registry_register_and_dispatch(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool())

    result = asyncio.run(registry.dispatch(name="fake", args={"x": "1"}, cwd=tmp_path))
    assert "ok:" in result
    assert str(tmp_path) in result
    assert result.endswith(":1")


def test_registry_tool_specs_after_register() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool())

    specs = registry.tool_specs()
    assert len(specs) == 1
    assert specs[0]["function"]["name"] == "fake"


def test_registry_unknown_tool_returns_error(tmp_path: Path) -> None:
    registry = ToolRegistry()

    result = asyncio.run(registry.dispatch(name="missing", args={}, cwd=tmp_path))
    assert result == "[ERROR] Unknown tool: missing"


def test_registry_handler_exception_returns_error(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_BoomTool())

    result = asyncio.run(registry.dispatch(name="boom", args={}, cwd=tmp_path))
    assert result == "[ERROR] Tool 'boom' failed (RuntimeError)"


def test_router_dispatch_with_json_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool())
    router = ToolRouter(registry)

    result = asyncio.run(router.dispatch(name="fake", arguments='{"x":"7"}', cwd=tmp_path))
    assert result.endswith(":7")


def test_router_rejects_invalid_json_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool())
    router = ToolRouter(registry)

    result = asyncio.run(router.dispatch(name="fake", arguments="{", cwd=tmp_path))
    assert result.startswith("[ERROR] Invalid tool arguments JSON:")


def test_router_rejects_non_object_json_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool())
    router = ToolRouter(registry)

    result = asyncio.run(router.dispatch(name="fake", arguments="[]", cwd=tmp_path))
    assert result == "[ERROR] Invalid tool arguments JSON: expected object"
