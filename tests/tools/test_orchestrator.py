from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pycodex.tools.orchestrator as orchestrator_module
import pytest
from pycodex.approval.policy import ApprovalPolicy, ApprovalStore, ReviewDecision
from pycodex.tools.base import ToolError, ToolResult
from pycodex.tools.orchestrator import ToolAborted, execute_with_approval
from pycodex.tools.shell import ShellTool

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


class _RaisingApprovalKeyMutatingTool(_MutatingTool):
    name = "raising_approval_key"

    def approval_key(self, args: dict[str, Any], cwd: Path) -> str:
        _ = args, cwd
        raise RuntimeError("boom")


class _CanonicalShellKeyMutatingTool(_MutatingTool):
    name = "shell"

    def approval_key(self, args: dict[str, Any], cwd: Path) -> dict[str, Any] | ToolError:
        return ShellTool().approval_key(args, cwd)


class _PromptLockProbeMutatingTool(_MutatingTool):
    def __init__(self, lock: asyncio.Lock) -> None:
        super().__init__()
        self._lock = lock

    async def handle(self, args: dict[str, Any], cwd: Path) -> ToolResult:
        await asyncio.wait_for(self._lock.acquire(), timeout=0.2)
        self._lock.release()
        return await super().handle(args, cwd)


AskUserFn = Callable[[Any, dict[str, Any]], Awaitable[ReviewDecision]]


async def _execute_tool(
    *,
    tool: Any,
    args: dict[str, Any],
    cwd: Path,
    policy: ApprovalPolicy,
    store: ApprovalStore,
    ask_user_fn: AskUserFn,
) -> ToolResult | ToolError:
    return await execute_with_approval(
        tool=tool,
        args=args,
        cwd=cwd,
        policy=policy,
        store=store,
        ask_user_fn=ask_user_fn,
    )


def _start_execute_tool_task(
    *,
    tool: Any,
    args: dict[str, Any],
    cwd: Path,
    policy: ApprovalPolicy,
    store: ApprovalStore,
    ask_user_fn: AskUserFn,
) -> asyncio.Task[ToolResult | ToolError]:
    return asyncio.create_task(
        _execute_tool(
            tool=tool,
            args=args,
            cwd=cwd,
            policy=policy,
            store=store,
            ask_user_fn=ask_user_fn,
        )
    )


async def _execute_with_constant_prompt_decision(
    *,
    tool: Any,
    args: dict[str, Any],
    cwd: Path,
    policy: ApprovalPolicy,
    store: ApprovalStore,
    decision: ReviewDecision,
) -> tuple[ToolResult | ToolError, int]:
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return decision

    outcome = await _execute_tool(
        tool=tool,
        args=args,
        cwd=cwd,
        policy=policy,
        store=store,
        ask_user_fn=ask_user_fn,
    )
    return outcome, ask_count


async def _run_parallel_shared_key_requests(
    *,
    tool: Any,
    store: ApprovalStore,
    cwd: Path,
    ask_user_fn: AskUserFn,
    first_prompt_entered: asyncio.Event,
    release_first_prompt: asyncio.Event,
) -> tuple[ToolResult | ToolError, ToolResult | ToolError]:
    task_one = _start_execute_tool_task(
        tool=tool,
        args={"x": 1},
        cwd=cwd,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )
    await first_prompt_entered.wait()
    task_two = _start_execute_tool_task(
        tool=tool,
        args={"x": 1},
        cwd=cwd,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )
    release_first_prompt.set()
    first, second = await asyncio.gather(task_one, task_two)
    return first, second


async def _execute_shell_pair(
    *,
    tool: _CanonicalShellKeyMutatingTool,
    store: ApprovalStore,
    cwd: Path,
    ask_user_fn: AskUserFn,
    first_args: dict[str, Any],
    second_args: dict[str, Any],
) -> tuple[ToolResult | ToolError, ToolResult | ToolError]:
    first = await _execute_tool(
        tool=tool,
        args=first_args,
        cwd=cwd,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )
    second = await _execute_tool(
        tool=tool,
        args=second_args,
        cwd=cwd,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )
    return first, second


async def _assert_parallel_prompts_once(
    *,
    tool: Any,
    store: ApprovalStore,
    cwd: Path,
) -> None:
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

    first, second = await _run_parallel_shared_key_requests(
        tool=tool,
        store=store,
        cwd=cwd,
        ask_user_fn=ask_user_fn,
        first_prompt_entered=first_prompt_entered,
        release_first_prompt=release_first_prompt,
    )

    assert isinstance(first, ToolResult)
    assert isinstance(second, ToolResult)
    assert ask_count == 1
    assert tool.calls == 2


async def test_execute_with_approval_read_only_bypasses_prompt(tmp_path: Path) -> None:
    tool = _ReadOnlyTool()
    store = ApprovalStore()
    outcome, ask_count = await _execute_with_constant_prompt_decision(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        decision=ReviewDecision.APPROVED,
    )

    assert isinstance(outcome, ToolResult)
    assert ask_count == 0
    assert tool.calls == 1


async def test_execute_with_approval_never_auto_approves_without_prompt(tmp_path: Path) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    outcome, ask_count = await _execute_with_constant_prompt_decision(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.NEVER,
        store=store,
        decision=ReviewDecision.DENIED,
    )

    assert isinstance(outcome, ToolResult)
    assert ask_count == 0
    assert tool.calls == 1


async def test_execute_with_approval_on_failure_auto_approves_without_prompt(
    tmp_path: Path,
) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    outcome, ask_count = await _execute_with_constant_prompt_decision(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_FAILURE,
        store=store,
        decision=ReviewDecision.DENIED,
    )

    assert isinstance(outcome, ToolResult)
    assert ask_count == 0
    assert tool.calls == 1


async def test_execute_with_approval_on_request_approved_executes_and_does_not_cache(
    tmp_path: Path,
) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    key = {"tool": "mutating", "args": {"x": 1}}
    outcome, ask_count = await _execute_with_constant_prompt_decision(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        decision=ReviewDecision.APPROVED,
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

    first = await _execute_tool(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )
    second = await _execute_tool(
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
    outcome, ask_count = await _execute_with_constant_prompt_decision(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        decision=ReviewDecision.DENIED,
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
        await _execute_tool(
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
    outcome, ask_count = await _execute_with_constant_prompt_decision(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        decision=ReviewDecision.APPROVED,
    )

    assert isinstance(outcome, ToolResult)
    assert ask_count == 0
    assert tool.calls == 1


async def test_execute_with_approval_uses_tool_specific_approval_key(tmp_path: Path) -> None:
    tool = _PathKeyMutatingTool()
    store = ApprovalStore()
    store.put("/tmp/example.txt", ReviewDecision.APPROVED_FOR_SESSION)
    outcome, ask_count = await _execute_with_constant_prompt_decision(
        tool=tool,
        args={"file_path": "x.txt", "content": "hi"},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        decision=ReviewDecision.APPROVED,
    )

    assert isinstance(outcome, ToolResult)
    assert ask_count == 0
    assert tool.calls == 1


async def test_execute_with_approval_canonicalizes_shell_wrapper_approval_key(
    tmp_path: Path,
) -> None:
    tool = _CanonicalShellKeyMutatingTool()
    store = ApprovalStore()
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.APPROVED_FOR_SESSION

    first_args = {"command": 'bash -lc "ls -la"'}
    second_args = {"command": '/bin/bash -lc "ls   -la"'}

    first, second = await _execute_shell_pair(
        tool=tool,
        store=store,
        cwd=tmp_path,
        ask_user_fn=ask_user_fn,
        first_args=first_args,
        second_args=second_args,
    )

    assert isinstance(first, ToolResult)
    assert isinstance(second, ToolResult)
    assert ask_count == 1
    assert tool.calls == 2
    assert tool.approval_key(first_args, tmp_path) == tool.approval_key(second_args, tmp_path)


async def test_execute_with_approval_keeps_shell_semantic_variants_separate(
    tmp_path: Path,
) -> None:
    tool = _CanonicalShellKeyMutatingTool()
    store = ApprovalStore()
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.APPROVED_FOR_SESSION

    first_args = {"command": 'bash -lc "echo $HOME"'}
    second_args = {"command": "bash -lc \"echo '$HOME'\""}

    first, second = await _execute_shell_pair(
        tool=tool,
        store=store,
        cwd=tmp_path,
        ask_user_fn=ask_user_fn,
        first_args=first_args,
        second_args=second_args,
    )

    assert isinstance(first, ToolResult)
    assert isinstance(second, ToolResult)
    assert ask_count == 2
    assert tool.calls == 2
    assert tool.approval_key(first_args, tmp_path) != tool.approval_key(second_args, tmp_path)


async def test_execute_with_approval_normalizes_approval_key_provider_exceptions(
    tmp_path: Path,
) -> None:
    tool = _RaisingApprovalKeyMutatingTool()
    store = ApprovalStore()
    outcome, ask_count = await _execute_with_constant_prompt_decision(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        decision=ReviewDecision.APPROVED,
    )

    assert isinstance(outcome, ToolError)
    assert outcome.code == "approval_key_error"
    assert "Failed to build approval key for tool 'raising_approval_key'" in outcome.message
    assert ask_count == 0
    assert tool.calls == 0


async def test_execute_with_approval_concurrent_shared_key_prompts_once(tmp_path: Path) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    await _assert_parallel_prompts_once(tool=tool, store=store, cwd=tmp_path)


async def test_execute_with_approval_prompt_callback_can_reenter_store_lock(
    tmp_path: Path,
) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        await asyncio.wait_for(store.prompt_lock.acquire(), timeout=0.2)
        store.prompt_lock.release()
        return ReviewDecision.APPROVED

    outcome = await _execute_tool(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )

    assert isinstance(outcome, ToolResult)
    assert tool.calls == 1


async def test_execute_with_approval_prompt_owner_cancellation_wakes_waiters(
    tmp_path: Path,
) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    ask_count = 0
    first_prompt_entered = asyncio.Event()

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        if ask_count == 1:
            first_prompt_entered.set()
            await asyncio.Event().wait()
        return ReviewDecision.APPROVED

    first_task = _start_execute_tool_task(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )
    await first_prompt_entered.wait()
    second_task = _start_execute_tool_task(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )
    await asyncio.sleep(0)

    first_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_task

    second_result = await asyncio.wait_for(second_task, timeout=0.5)

    assert isinstance(second_result, ToolResult)
    assert ask_count == 2
    assert tool.calls == 1


async def test_execute_with_approval_cached_waiter_path_runs_outside_prompt_lock(
    tmp_path: Path,
) -> None:
    store = ApprovalStore()
    tool = _PromptLockProbeMutatingTool(store.prompt_lock)
    await _assert_parallel_prompts_once(tool=tool, store=store, cwd=tmp_path)


async def test_execute_with_approval_prompt_owner_cancelled_during_finalize_wakes_waiters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _MutatingTool()
    store = ApprovalStore()
    ask_count = 0
    first_prompt_entered = asyncio.Event()
    release_first_prompt = asyncio.Event()
    finalize_started = asyncio.Event()
    release_finalize = asyncio.Event()
    original_finalize = orchestrator_module._finalize_pending_prompt

    async def wrapped_finalize(
        *,
        store: ApprovalStore,
        key: object,
        decision: ReviewDecision | None,
    ) -> None:
        finalize_started.set()
        await release_finalize.wait()
        await original_finalize(store=store, key=key, decision=decision)

    monkeypatch.setattr(orchestrator_module, "_finalize_pending_prompt", wrapped_finalize)

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        if ask_count == 1:
            first_prompt_entered.set()
            await release_first_prompt.wait()
        return ReviewDecision.APPROVED_FOR_SESSION

    first_task = _start_execute_tool_task(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )
    await first_prompt_entered.wait()
    second_task = _start_execute_tool_task(
        tool=tool,
        args={"x": 1},
        cwd=tmp_path,
        policy=ApprovalPolicy.ON_REQUEST,
        store=store,
        ask_user_fn=ask_user_fn,
    )
    release_first_prompt.set()
    await finalize_started.wait()

    first_task.cancel()
    release_finalize.set()

    with pytest.raises(asyncio.CancelledError):
        await first_task

    second_result = await asyncio.wait_for(second_task, timeout=0.5)

    assert isinstance(second_result, ToolResult)
    assert ask_count == 1
    assert tool.calls == 1
