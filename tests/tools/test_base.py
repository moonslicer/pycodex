from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pycodex.tools.base import ToolRegistry, ToolResult, ToolRouter


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

    async def handle(self, args: dict[str, Any], cwd: Path) -> ToolResult:
        return ToolResult(body=f"ok:{cwd}:{args.get('x', '')}")


class _BoomTool(_FakeTool):
    name = "boom"

    async def handle(self, args: dict[str, Any], cwd: Path) -> ToolResult:
        _ = args, cwd
        raise RuntimeError("explode")


def _decode_outcome_payload(payload: str) -> dict[str, Any]:
    decoded = json.loads(payload)
    assert isinstance(decoded, dict)
    assert isinstance(decoded.get("success"), bool)
    return decoded


def test_registry_starts_empty() -> None:
    registry = ToolRegistry()
    assert registry.tool_specs() == []


async def test_registry_register_and_dispatch(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool())

    result = await registry.dispatch(name="fake", args={"x": "1"}, cwd=tmp_path)
    payload = _decode_outcome_payload(result)

    assert payload["success"] is True
    body = payload["body"]
    assert isinstance(body, str)
    assert "ok:" in body
    assert str(tmp_path) in body
    assert body.endswith(":1")


def test_registry_tool_specs_after_register() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool())

    specs = registry.tool_specs()
    assert len(specs) == 1
    assert specs[0]["function"]["name"] == "fake"


async def test_registry_unknown_tool_returns_error(tmp_path: Path) -> None:
    registry = ToolRegistry()

    result = await registry.dispatch(name="missing", args={}, cwd=tmp_path)
    payload = _decode_outcome_payload(result)

    assert payload["success"] is False
    assert payload["body"] == "Unknown tool: missing"
    assert payload["error"] == {
        "message": "Unknown tool: missing",
        "code": "unknown",
    }


async def test_registry_handler_exception_returns_error(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_BoomTool())

    result = await registry.dispatch(name="boom", args={}, cwd=tmp_path)
    payload = _decode_outcome_payload(result)

    assert payload["success"] is False
    assert payload["body"] == "Tool 'boom' failed (RuntimeError)"
    assert payload["error"] == {
        "message": "Tool 'boom' failed (RuntimeError)",
        "code": "handler_exception",
    }


async def test_router_dispatch_with_json_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool())
    router = ToolRouter(registry)

    result = await router.dispatch(name="fake", arguments='{"x":"7"}', cwd=tmp_path)
    payload = _decode_outcome_payload(result)

    assert payload["success"] is True
    body = payload["body"]
    assert isinstance(body, str)
    assert body.endswith(":7")


async def test_router_rejects_invalid_json_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool())
    router = ToolRouter(registry)

    result = await router.dispatch(name="fake", arguments="{", cwd=tmp_path)
    payload = _decode_outcome_payload(result)

    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_arguments_json"
    body = payload["body"]
    assert isinstance(body, str)
    assert body.startswith("Invalid tool arguments JSON:")


async def test_router_rejects_non_object_json_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool())
    router = ToolRouter(registry)

    result = await router.dispatch(name="fake", arguments="[]", cwd=tmp_path)
    payload = _decode_outcome_payload(result)

    assert payload["success"] is False
    assert payload["body"] == "Invalid tool arguments JSON: expected object"
    assert payload["error"]["code"] == "invalid_arguments_json"
