from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pycodex.approval.policy import ApprovalPolicy, ApprovalStore, ReviewDecision
from pycodex.tools.base import ToolError, ToolRegistry, ToolResult, ToolRouter
from pycodex.tools.orchestrator import OrchestratorConfig, ToolAborted
from pycodex.tools.write_file import WriteFileTool


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


class _MutatingTool(_FakeTool):
    name = "mutating"

    def __init__(self) -> None:
        self.calls = 0

    async def is_mutating(self, args: dict[str, Any]) -> bool:
        _ = args
        return True

    async def handle(self, args: dict[str, Any], cwd: Path) -> ToolResult:
        self.calls += 1
        return ToolResult(body=f"ok:{cwd}:{args.get('x', '')}")


class _ApprovalKeyErrorTool(_MutatingTool):
    name = "approval_key_error"

    def approval_key(self, args: dict[str, Any], cwd: Path) -> ToolError:
        _ = args, cwd
        return ToolError(message="bad approval key", code="bad_key")


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


async def test_registry_dispatch_uses_orchestrator_when_configured(tmp_path: Path) -> None:
    tool = _MutatingTool()
    asked = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal asked
        asked += 1
        return ReviewDecision.APPROVED

    registry = ToolRegistry(
        orchestrator=OrchestratorConfig(
            policy=ApprovalPolicy.ON_REQUEST,
            store=ApprovalStore(),
            ask_user_fn=ask_user_fn,
        )
    )
    registry.register(tool)

    result = await registry.dispatch(name="mutating", args={"x": "9"}, cwd=tmp_path)
    payload = _decode_outcome_payload(result)

    assert payload["success"] is True
    assert asked == 1
    assert tool.calls == 1


async def test_registry_dispatch_propagates_tool_aborted(tmp_path: Path) -> None:
    tool = _MutatingTool()

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        return ReviewDecision.ABORT

    registry = ToolRegistry(
        orchestrator=OrchestratorConfig(
            policy=ApprovalPolicy.ON_REQUEST,
            store=ApprovalStore(),
            ask_user_fn=ask_user_fn,
        )
    )
    registry.register(tool)

    with pytest.raises(ToolAborted, match="mutating"):
        await registry.dispatch(name="mutating", args={"x": "9"}, cwd=tmp_path)

    assert tool.calls == 0


async def test_registry_dispatch_propagates_approval_key_errors(tmp_path: Path) -> None:
    tool = _ApprovalKeyErrorTool()
    asked = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal asked
        asked += 1
        return ReviewDecision.APPROVED

    registry = ToolRegistry(
        orchestrator=OrchestratorConfig(
            policy=ApprovalPolicy.ON_REQUEST,
            store=ApprovalStore(),
            ask_user_fn=ask_user_fn,
        )
    )
    registry.register(tool)

    result = await registry.dispatch(name="approval_key_error", args={"x": "1"}, cwd=tmp_path)
    payload = _decode_outcome_payload(result)

    assert payload["success"] is False
    assert payload["body"] == "bad approval key"
    assert payload["error"] == {
        "message": "bad approval key",
        "code": "bad_key",
    }
    assert asked == 0
    assert tool.calls == 0


async def test_registry_write_file_approval_cache_is_isolated_per_file_path(tmp_path: Path) -> None:
    asked = 0
    store = ApprovalStore()

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal asked
        asked += 1
        return ReviewDecision.APPROVED_FOR_SESSION

    registry = ToolRegistry(
        orchestrator=OrchestratorConfig(
            policy=ApprovalPolicy.ON_REQUEST,
            store=store,
            ask_user_fn=ask_user_fn,
        )
    )
    registry.register(WriteFileTool())

    first = _decode_outcome_payload(
        await registry.dispatch(
            name="write_file",
            args={"file_path": "a.txt", "content": "first"},
            cwd=tmp_path,
        )
    )
    second_same_path = _decode_outcome_payload(
        await registry.dispatch(
            name="write_file",
            args={"file_path": "a.txt", "content": "first-again"},
            cwd=tmp_path,
        )
    )
    third_other_path = _decode_outcome_payload(
        await registry.dispatch(
            name="write_file",
            args={"file_path": "b.txt", "content": "second"},
            cwd=tmp_path,
        )
    )

    assert first["success"] is True
    assert second_same_path["success"] is True
    assert third_other_path["success"] is True
    assert asked == 2
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "first-again"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "second"


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
