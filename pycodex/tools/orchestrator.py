"""Approval orchestration for tool execution."""

from __future__ import annotations

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
    decision: ReviewDecision | None = None
    execute_after_lock = False
    async with store.prompt_lock:
        if store.get(key) == ReviewDecision.APPROVED_FOR_SESSION:
            execute_after_lock = True
        else:
            decision = await ask_user_fn(tool, args)
            store.put(key, decision)

    if execute_after_lock:
        return await tool.handle(args, cwd)

    assert decision is not None  # narrowed by the non-cache path above
    if decision == ReviewDecision.ABORT:
        raise ToolAborted(tool.name)

    if decision == ReviewDecision.DENIED:
        return ToolError(message="Operation denied by user.", code="denied")

    return await tool.handle(args, cwd)


def _approval_key(*, tool: ToolHandler, args: dict[str, Any], cwd: Path) -> object | ToolError:
    maybe_provider = getattr(tool, "approval_key", None)
    if callable(maybe_provider):
        provider = cast(Callable[[dict[str, Any], Path], object | ToolError], maybe_provider)
        return provider(args, cwd)

    return {"tool": tool.name, "args": args}
