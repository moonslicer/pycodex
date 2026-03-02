"""Compaction strategy and implementation interfaces plus default components."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pycodex.core.session import PromptItem, Session, TokenUsageCounts

DEFAULT_COMPACTION_STRATEGY = "threshold_v1"
DEFAULT_COMPACTION_IMPLEMENTATION = "local_summary_v1"
DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
DEFAULT_SUMMARY_MAX_CHARS = 1_200

_SUMMARY_BLOCK_MARKER = "[compaction.summary.v1]"


@dataclass(frozen=True, slots=True)
class CompactionContext:
    """Inputs used by a compaction strategy to decide whether to compact."""

    history: list[PromptItem]
    cumulative_usage: TokenUsageCounts
    context_window_tokens: int


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    """Decision output from a compaction strategy."""

    replace_end: int
    used_tokens: int
    remaining_ratio: float


@dataclass(frozen=True, slots=True)
class SummaryRequest:
    """Input payload for summary generation implementations."""

    items: list[PromptItem]
    max_chars: int


@dataclass(frozen=True, slots=True)
class SummaryOutput:
    """Summary generation output."""

    text: str


@dataclass(frozen=True, slots=True)
class CompactionApplied:
    """Metadata describing an applied compaction."""

    strategy: str
    implementation: str
    replace_end: int
    summary_text: str


class CompactionStrategy(Protocol):
    """Interface for deciding when and what range to compact."""

    name: str

    def plan(self, context: CompactionContext) -> CompactionPlan | None:
        """Return a compaction plan or ``None`` when compaction is not needed."""


class CompactionImplementation(Protocol):
    """Interface for generating summary content for a compaction plan."""

    name: str

    def summarize(self, request: SummaryRequest) -> SummaryOutput:
        """Return deterministic summary output for the requested prompt items."""


@dataclass(slots=True)
class ThresholdV1Strategy:
    """Ratio-threshold compaction strategy."""

    threshold_ratio: float = 0.2
    keep_recent_items: int = 8
    min_replace_items: int = 2
    name: str = DEFAULT_COMPACTION_STRATEGY

    def plan(self, context: CompactionContext) -> CompactionPlan | None:
        if context.context_window_tokens <= 0:
            return None
        if len(context.history) <= self.keep_recent_items:
            return None

        used_tokens = (
            context.cumulative_usage["input_tokens"] + context.cumulative_usage["output_tokens"]
        )
        remaining_tokens = max(context.context_window_tokens - used_tokens, 0)
        remaining_ratio = remaining_tokens / context.context_window_tokens
        if remaining_ratio >= self.threshold_ratio:
            return None

        replace_end = len(context.history) - self.keep_recent_items
        if replace_end < self.min_replace_items:
            return None

        return CompactionPlan(
            replace_end=replace_end,
            used_tokens=used_tokens,
            remaining_ratio=remaining_ratio,
        )


@dataclass(slots=True)
class LocalSummaryV1Implementation:
    """Deterministic local summary generation implementation."""

    max_lines: int = 8
    max_line_chars: int = 120
    name: str = DEFAULT_COMPACTION_IMPLEMENTATION

    def summarize(self, request: SummaryRequest) -> SummaryOutput:
        lines: list[str] = []
        for item in request.items[: self.max_lines]:
            lines.append(f"- {_summarize_item(item, max_chars=self.max_line_chars)}")

        remaining = len(request.items) - min(len(request.items), self.max_lines)
        if remaining > 0:
            lines.append(f"- ... {remaining} additional items omitted")

        if not lines:
            text = "No historical items available for summary."
        else:
            text = "Conversation summary:\n" + "\n".join(lines)

        if len(text) > request.max_chars:
            text = f"{text[: request.max_chars]}..."
        return SummaryOutput(text=text)


@dataclass(slots=True)
class CompactionOrchestrator:
    """Apply strategy + implementation to compact session history."""

    strategy: CompactionStrategy
    implementation: CompactionImplementation
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS
    summary_max_chars: int = DEFAULT_SUMMARY_MAX_CHARS

    def compact(self, session: Session) -> CompactionApplied | None:
        history = session.to_prompt()
        context = CompactionContext(
            history=history,
            cumulative_usage=session.cumulative_usage(),
            context_window_tokens=self.context_window_tokens,
        )
        plan = self.strategy.plan(context)
        if plan is None:
            return None

        items_to_replace = history[: plan.replace_end]
        summary_output = self.implementation.summarize(
            SummaryRequest(items=items_to_replace, max_chars=self.summary_max_chars)
        )
        summary_text = _render_summary_block(summary=summary_output.text)
        replaced = session.replace_prefix_with_system_summary(
            replace_count=plan.replace_end,
            summary_text=summary_text,
        )
        if not replaced:
            return None

        return CompactionApplied(
            strategy=self.strategy.name,
            implementation=self.implementation.name,
            replace_end=plan.replace_end,
            summary_text=summary_text,
        )


def create_compaction_orchestrator(
    *,
    strategy_name: str = DEFAULT_COMPACTION_STRATEGY,
    implementation_name: str = DEFAULT_COMPACTION_IMPLEMENTATION,
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS,
    summary_max_chars: int = DEFAULT_SUMMARY_MAX_CHARS,
) -> CompactionOrchestrator:
    """Build a compaction orchestrator from named components."""
    strategy_factory = STRATEGY_REGISTRY.get(strategy_name)
    if strategy_factory is None:
        known = ", ".join(sorted(STRATEGY_REGISTRY))
        raise ValueError(f"Unknown compaction strategy {strategy_name!r}. Known: {known}")

    implementation_factory = IMPLEMENTATION_REGISTRY.get(implementation_name)
    if implementation_factory is None:
        known = ", ".join(sorted(IMPLEMENTATION_REGISTRY))
        raise ValueError(
            f"Unknown compaction implementation {implementation_name!r}. Known: {known}"
        )

    return CompactionOrchestrator(
        strategy=strategy_factory(),
        implementation=implementation_factory(),
        context_window_tokens=context_window_tokens,
        summary_max_chars=summary_max_chars,
    )


def _build_threshold_v1_strategy() -> CompactionStrategy:
    return ThresholdV1Strategy()


def _build_local_summary_v1_implementation() -> CompactionImplementation:
    return LocalSummaryV1Implementation()


STRATEGY_REGISTRY: dict[str, Callable[[], CompactionStrategy]] = {
    DEFAULT_COMPACTION_STRATEGY: _build_threshold_v1_strategy,
}
IMPLEMENTATION_REGISTRY: dict[str, Callable[[], CompactionImplementation]] = {
    DEFAULT_COMPACTION_IMPLEMENTATION: _build_local_summary_v1_implementation,
}


def _render_summary_block(
    *,
    summary: str,
) -> str:
    body = summary.strip() or "No summary content."
    return f"{_SUMMARY_BLOCK_MARKER}\n{body}"


def _summarize_item(item: PromptItem, *, max_chars: int) -> str:
    item_type = item.get("type")
    if item_type == "function_call":
        name = item.get("name", "unknown")
        arguments = item.get("arguments", "{}")
        text = f"function_call {name} args={arguments}"
        return _truncate(text, max_chars=max_chars)

    role = item.get("role")
    if role == "tool":
        call_id = item.get("tool_call_id", "")
        content = item.get("content", "")
        text = f"tool_result {call_id}: {content}"
        return _truncate(text, max_chars=max_chars)

    content = item.get("content", "")
    text = f"{role}: {content}"
    return _truncate(text, max_chars=max_chars)


def _truncate(text: object, *, max_chars: int) -> str:
    rendered = str(text).replace("\n", "\\n")
    if len(rendered) <= max_chars:
        return rendered
    return f"{rendered[:max_chars]}..."
