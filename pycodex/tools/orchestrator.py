"""Approval orchestration for tool execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pycodex.approval.exec_policy import ExecDecision
from pycodex.approval.policy import ApprovalPolicy, ApprovalStore, ReviewDecision
from pycodex.approval.sandbox import SandboxPolicy, SandboxUnavailable
from pycodex.tools.outcome import ToolError, ToolOutcome

if TYPE_CHECKING:
    from pycodex.tools.base import ToolHandler

AskUserFn = Callable[["ToolHandler", dict[str, Any]], Awaitable[ReviewDecision]]
ExecPolicyFn = Callable[[str], ExecDecision]


@dataclass(slots=True, frozen=True)
class OrchestratorConfig:
    """Configuration bundle required for approval-aware dispatch."""

    policy: ApprovalPolicy
    store: ApprovalStore
    ask_user_fn: AskUserFn
    exec_policy_fn: ExecPolicyFn | None = None
    sandbox_policy: SandboxPolicy | None = None


class ToolAborted(Exception):
    """Raised when the user aborts tool execution for the active turn.

    The caller must treat this as terminal for the current turn.
    """

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Tool execution aborted by user: {tool_name}")
        self.tool_name = tool_name


async def execute_with_approval(
    *,
    tool: ToolHandler,
    args: dict[str, Any],
    cwd: Path,
    policy: ApprovalPolicy,
    store: ApprovalStore,
    ask_user_fn: AskUserFn,
    exec_policy_fn: ExecPolicyFn | None = None,
    sandbox_policy: SandboxPolicy | None = None,
) -> ToolOutcome:
    """Execute a tool call with approval handling for mutating operations.

    `ReviewDecision.ABORT` raises `ToolAborted` so upstream callers can stop
    the active turn immediately.
    """
    if not await tool.is_mutating(args):
        return await tool.handle(args, cwd)

    key = _approval_key(tool=tool, args=args, cwd=cwd)
    if isinstance(key, ToolError):
        return key

    if exec_policy_fn is not None:
        canonical_command = _canonical_command(tool=tool, args=args)
        if canonical_command is not None:
            exec_decision = exec_policy_fn(canonical_command)
            if exec_decision == ExecDecision.FORBIDDEN:
                return ToolError(
                    message="Command blocked by exec policy.",
                    code="forbidden",
                )
            if exec_decision == ExecDecision.ALLOW:
                if sandbox_policy is None or sandbox_policy == SandboxPolicy.DANGER_FULL_ACCESS:
                    return await tool.handle(args, cwd)
                return await _run_sandboxed(
                    tool=tool,
                    args=args,
                    cwd=cwd,
                    sandbox_policy=sandbox_policy,
                )

    if sandbox_policy is None or sandbox_policy == SandboxPolicy.DANGER_FULL_ACCESS:
        return await _execute_with_standard_approval(
            tool=tool,
            args=args,
            cwd=cwd,
            key=key,
            policy=policy,
            store=store,
            ask_user_fn=ask_user_fn,
        )

    restrictive_policy = sandbox_policy

    if policy == ApprovalPolicy.NEVER:
        return await _run_sandboxed(
            tool=tool,
            args=args,
            cwd=cwd,
            sandbox_policy=restrictive_policy,
        )

    if policy == ApprovalPolicy.ON_FAILURE:
        sandbox_outcome = await _run_sandboxed(
            tool=tool,
            args=args,
            cwd=cwd,
            sandbox_policy=restrictive_policy,
        )
        if not _is_sandbox_denial(sandbox_outcome):
            return sandbox_outcome

        retry_decision = await ask_user_fn(tool, args)
        if retry_decision == ReviewDecision.ABORT:
            raise ToolAborted(tool.name)
        if retry_decision == ReviewDecision.DENIED:
            return ToolError(message="Operation denied by user.", code="denied")

        store.put(key, retry_decision)
        return await tool.handle(args, cwd)

    return await _execute_with_standard_approval(
        tool=tool,
        args=args,
        cwd=cwd,
        key=key,
        policy=policy,
        store=store,
        ask_user_fn=ask_user_fn,
        sandbox_policy=restrictive_policy,
    )


async def _execute_with_standard_approval(
    *,
    tool: ToolHandler,
    args: dict[str, Any],
    cwd: Path,
    key: object,
    policy: ApprovalPolicy,
    store: ApprovalStore,
    ask_user_fn: AskUserFn,
    sandbox_policy: SandboxPolicy | None = None,
) -> ToolOutcome:
    if store.get(key) == ReviewDecision.APPROVED_FOR_SESSION:
        if sandbox_policy is None or sandbox_policy == SandboxPolicy.DANGER_FULL_ACCESS:
            return await tool.handle(args, cwd)
        restrictive_policy = sandbox_policy
        return await _run_sandboxed(
            tool=tool,
            args=args,
            cwd=cwd,
            sandbox_policy=restrictive_policy,
        )

    if policy in (ApprovalPolicy.NEVER, ApprovalPolicy.ON_FAILURE):
        if sandbox_policy is None or sandbox_policy == SandboxPolicy.DANGER_FULL_ACCESS:
            return await tool.handle(args, cwd)
        restrictive_policy = sandbox_policy
        return await _run_sandboxed(
            tool=tool,
            args=args,
            cwd=cwd,
            sandbox_policy=restrictive_policy,
        )

    # Remaining policies (ON_REQUEST / UNLESS_TRUSTED) require explicit user review.
    # ask_user_fn must run outside prompt_lock to avoid callback re-entrancy deadlocks.
    while True:
        owns_prompt = False
        pending_prompt: asyncio.Event | None = None
        execute_cached_path = False

        async with store.prompt_lock:
            if store.get(key) == ReviewDecision.APPROVED_FOR_SESSION:
                execute_cached_path = True
            else:
                # A pending event means another coroutine is already collecting a user decision
                # for this exact approval key.
                pending_prompt = store.get_pending_prompt(key)
                if pending_prompt is None:
                    # This coroutine becomes the "prompt owner" for this key and is responsible
                    # for waking waiters once a decision is produced (or fails).
                    pending_prompt = store.create_pending_prompt(key)
                    owns_prompt = True

        if execute_cached_path:
            if sandbox_policy is None or sandbox_policy == SandboxPolicy.DANGER_FULL_ACCESS:
                return await tool.handle(args, cwd)
            restrictive_policy = sandbox_policy
            return await _run_sandboxed(
                tool=tool,
                args=args,
                cwd=cwd,
                sandbox_policy=restrictive_policy,
            )

        if not owns_prompt:
            # Another coroutine owns this prompt; wait until it publishes a decision and then
            # re-enter the loop to re-check cache / policy state.
            assert pending_prompt is not None
            await pending_prompt.wait()
            continue

        decision: ReviewDecision | None = None
        try:
            # Important: this runs outside prompt_lock. The callback may perform work that
            # itself needs the lock (directly or indirectly), and holding the lock here could
            # deadlock re-entrant paths.
            decision = await ask_user_fn(tool, args)
        finally:
            # Always clear and publish pending state, even when the owner task is cancelled.
            await asyncio.shield(_finalize_pending_prompt(store=store, key=key, decision=decision))

        assert decision is not None

        if decision == ReviewDecision.ABORT:
            # ABORT is a terminal control-flow signal for the active turn.
            raise ToolAborted(tool.name)

        if decision == ReviewDecision.DENIED:
            return ToolError(message="Operation denied by user.", code="denied")

        if sandbox_policy is None or sandbox_policy == SandboxPolicy.DANGER_FULL_ACCESS:
            return await tool.handle(args, cwd)
        restrictive_policy = sandbox_policy
        return await _run_sandboxed(
            tool=tool,
            args=args,
            cwd=cwd,
            sandbox_policy=restrictive_policy,
        )


def _canonical_command(*, tool: ToolHandler, args: dict[str, Any]) -> str | None:
    maybe_provider = getattr(tool, "canonical_command", None)
    if not callable(maybe_provider):
        return None
    provider = cast(Callable[[dict[str, Any]], str | None], maybe_provider)
    return provider(args)


async def _sandbox_execute(
    *,
    tool: ToolHandler,
    args: dict[str, Any],
    cwd: Path,
    policy: SandboxPolicy,
) -> ToolOutcome:
    maybe_executor = getattr(tool, "sandbox_execute", None)
    if not callable(maybe_executor):
        return await tool.handle(args, cwd)
    executor = cast(
        Callable[[dict[str, Any], Path, SandboxPolicy], Awaitable[ToolOutcome]], maybe_executor
    )
    return await executor(args, cwd, policy)


async def _run_sandboxed(
    *,
    tool: ToolHandler,
    args: dict[str, Any],
    cwd: Path,
    sandbox_policy: SandboxPolicy,
) -> ToolOutcome:
    try:
        outcome = await _sandbox_execute(
            tool=tool,
            args=args,
            cwd=cwd,
            policy=sandbox_policy,
        )
    except SandboxUnavailable as exc:
        return ToolError(message=str(exc), code="sandbox_unavailable")
    if _is_sandbox_denial(outcome):
        return ToolError(message="Command blocked by sandbox.", code="sandbox_blocked")
    return outcome


def _is_sandbox_denial(outcome: ToolOutcome) -> bool:
    if isinstance(outcome, ToolError):
        return outcome.code in {"sandbox_blocked", "sandbox_denied"}

    if not isinstance(outcome.body, dict):
        return False
    metadata = outcome.body.get("metadata")
    if not isinstance(metadata, dict):
        return False
    exit_code = metadata.get("exit_code")
    return isinstance(exit_code, int) and exit_code != 0


def _approval_key(*, tool: ToolHandler, args: dict[str, Any], cwd: Path) -> object | ToolError:
    maybe_provider = getattr(tool, "approval_key", None)
    if callable(maybe_provider):
        provider = cast(Callable[[dict[str, Any], Path], object | ToolError], maybe_provider)
        try:
            return provider(args, cwd)
        except Exception as exc:
            return ToolError(
                message=f"Failed to build approval key for tool '{tool.name}': {type(exc).__name__}",
                code="approval_key_error",
            )

    return {"tool": tool.name, "args": args}


async def _finalize_pending_prompt(
    *,
    store: ApprovalStore,
    key: object,
    decision: ReviewDecision | None,
) -> None:
    """Finalize owner state for one pending prompt key and wake waiters."""
    async with store.prompt_lock:
        if decision is not None:
            store.put(key, decision)
        pending = store.clear_pending_prompt(key)
        if pending is not None:
            pending.set()
