"""Approval orchestration for tool execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pycodex.approval.policy import ApprovalPolicy, ApprovalStore, ReviewDecision
from pycodex.tools.outcome import ToolError, ToolOutcome

if TYPE_CHECKING:
    from pycodex.tools.base import ToolHandler

AskUserFn = Callable[["ToolHandler", dict[str, Any]], Awaitable[ReviewDecision]]


@dataclass(slots=True, frozen=True)
class OrchestratorConfig:
    """Configuration bundle required for approval-aware dispatch."""

    policy: ApprovalPolicy
    store: ApprovalStore
    ask_user_fn: AskUserFn


class ToolAborted(Exception):
    """Raised when the user aborts the active tool execution."""

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
) -> ToolOutcome:
    """Execute a tool call with approval handling for mutating operations."""
    if not await tool.is_mutating(args):
        return await tool.handle(args, cwd)

    key = _approval_key(tool=tool, args=args, cwd=cwd)
    if isinstance(key, ToolError):
        return key

    if store.get(key) == ReviewDecision.APPROVED_FOR_SESSION:
        return await tool.handle(args, cwd)

    if policy in (ApprovalPolicy.NEVER, ApprovalPolicy.ON_FAILURE):
        return await tool.handle(args, cwd)

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
            return await tool.handle(args, cwd)

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
            raise ToolAborted(tool.name)

        if decision == ReviewDecision.DENIED:
            return ToolError(message="Operation denied by user.", code="denied")

        return await tool.handle(args, cwd)


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
