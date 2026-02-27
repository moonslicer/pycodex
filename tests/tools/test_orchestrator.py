from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pycodex.approval.policy import ApprovalPolicy, ApprovalStore, ReviewDecision
from pycodex.tools.base import ToolError, ToolResult
from pycodex.tools.orchestrator import ToolAborted, execute_with_approval

pytestmark = pytest.mark.unit


class _ReadOnlyTool:
    name = "read_only"

    def __init__(self) -> None:
        self.calls = 0

    async def is_mutating(self, args: dict[str, Any]) -> bool:
        _ = args
        return False

    async def handle(self, args: dict[str, Any], cwd: Path) -> ToolResult:
        self.calls += 1
        return ToolResult(body={"args": args, "cwd": str(cwd)})


class _MutatingTool:
    name = "mutating"

    def __init__(self) -> None:
        self.calls = 0

    async def is_mutating(self, args: dict[str, Any]) -> bool:
        _ = args
        return True

    async def handle(self, args: dict[str, Any], cwd: Path) -> ToolResult:
        self.calls += 1
        return ToolResult(body={"args": args, "cwd": str(cwd)})


class _PathKeyMutatingTool(_MutatingTool):
    name = "write_file"

    def approval_key(self, args: dict[str, Any], cwd: Path) -> str:
        _ = args, cwd
        return "/tmp/example.txt"


async def test_execute_with_approval_read_only_bypasses_prompt(tmp_path: Path) -> None:
    tool = _ReadOnlyTool()
    store = ApprovalStore()
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.APPROVED

    outcome = await execute_with_approval(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )

    assert isinstance(outcome, ToolResult)
    assert ask_count == 0
    assert tool.calls == 1


async def test_execute_with_approval_never_auto_approves_without_prompt(tmp_path: Path) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.DENIED

    outcome = await execute_with_approval(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.NEVER,
        store=store,
        ask_user_fn=ask_user_fn,
    )

    assert isinstance(outcome, ToolResult)
    assert ask_count == 0
    assert tool.calls == 1


async def test_execute_with_approval_on_failure_auto_approves_without_prompt(
    tmp_path: Path,
) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.DENIED

    outcome = await execute_with_approval(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_FAILURE,
        store=store,
        ask_user_fn=ask_user_fn,
    )

    assert isinstance(outcome, ToolResult)
    assert ask_count == 0
    assert tool.calls == 1


async def test_execute_with_approval_on_request_approved_executes_and_does_not_cache(
    tmp_path: Path,
) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    ask_count = 0
    key = {"tool": "mutating", "args": {"x": 1}}

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.APPROVED

    outcome = await execute_with_approval(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )

    assert isinstance(outcome, ToolResult)
    assert ask_count == 1
    assert tool.calls == 1
    assert store.get(key) is None


async def test_execute_with_approval_on_request_approved_for_session_caches(
    tmp_path: Path,
) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    ask_count = 0
    key = {"tool": "mutating", "args": {"x": 1}}

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.APPROVED_FOR_SESSION

    first = await execute_with_approval(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )
    second = await execute_with_approval(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )

    assert isinstance(first, ToolResult)
    assert isinstance(second, ToolResult)
    assert ask_count == 1
    assert tool.calls == 2
    assert store.get(key) == ReviewDecision.APPROVED_FOR_SESSION


async def test_execute_with_approval_denied_returns_tool_error(tmp_path: Path) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.DENIED

    outcome = await execute_with_approval(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )

    assert isinstance(outcome, ToolError)
    assert outcome.code == "denied"
    assert ask_count == 1
    assert tool.calls == 0


async def test_execute_with_approval_abort_raises_tool_aborted(tmp_path: Path) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        return ReviewDecision.ABORT

    with pytest.raises(ToolAborted, match="mutating"):
        await execute_with_approval(
            tool=tool,
            args={"x": 1},
            cwd=tmp_path,
            policy=ApprovalPolicy.ON_REQUEST,
            store=store,
            ask_user_fn=ask_user_fn,
        )

    assert tool.calls == 0


async def test_execute_with_approval_cache_hit_skips_prompt(tmp_path: Path) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    key = {"tool": "mutating", "args": {"x": 1}}
    store.put(key, ReviewDecision.APPROVED_FOR_SESSION)
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.APPROVED

    outcome = await execute_with_approval(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )

    assert isinstance(outcome, ToolResult)
    assert ask_count == 0
    assert tool.calls == 1


async def test_execute_with_approval_uses_tool_specific_approval_key(tmp_path: Path) -> None:
    tool = _PathKeyMutatingTool()
    store = ApprovalStore()
    store.put("/tmp/example.txt", ReviewDecision.APPROVED_FOR_SESSION)
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.APPROVED

    outcome = await execute_with_approval(
        tool=tool,
        args={"file_path": "x.txt", "content": "hi"},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )

    assert isinstance(outcome, ToolResult)
    assert ask_count == 0
    assert tool.calls == 1


async def test_execute_with_approval_concurrent_shared_key_prompts_once(tmp_path: Path) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    ask_count = 0
    first_prompt_entered = asyncio.Event()
    release_first_prompt = asyncio.Event()

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        if ask_count == 1:
            first_prompt_entered.set()
            await release_first_prompt.wait()
        return ReviewDecision.APPROVED_FOR_SESSION

    task_one = asyncio.create_task(
        execute_with_approval(
            tool=tool,
            args={"x": 1},
            cwd=tmp_path,
            policy=ApprovalPolicy.ON_REQUEST,
            store=store,
            ask_user_fn=ask_user_fn,
        )
    )
    await first_prompt_entered.wait()
    task_two = asyncio.create_task(
        execute_with_approval(
            tool=tool,
            args={"x": 1},
            cwd=tmp_path,
            policy=ApprovalPolicy.ON_REQUEST,
            store=store,
            ask_user_fn=ask_user_fn,
        )
    )
    release_first_prompt.set()

    first, second = await asyncio.gather(task_one, task_two)

    assert isinstance(first, ToolResult)
    assert isinstance(second, ToolResult)
    assert ask_count == 1
    assert tool.calls == 2
