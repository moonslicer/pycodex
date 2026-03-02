"""Compaction strategy and implementation interfaces plus default components."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pycodex.core.session import PromptItem, Session

DEFAULT_COMPACTION_STRATEGY = "threshold_v1"
DEFAULT_COMPACTION_IMPLEMENTATION = "local_summary_v1"
DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
DEFAULT_SUMMARY_MAX_CHARS = 1_200
_CHARS_PER_TOKEN_ESTIMATE = 4

_SUMMARY_BLOCK_MARKER = "[compaction.summary.v1]"


@dataclass(frozen=True, slots=True)
class CompactionContext:
    """Inputs used by a compaction strategy to decide whether to compact."""

    history: list[PromptItem]
    prompt_tokens_estimate: int
    context_window_tokens: int


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    """Decision output from a compaction strategy."""

    replace_end: int
    used_tokens: int
    remaining_ratio: float
    threshold_ratio: float


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
    replaced_items: int
    estimated_prompt_tokens: int
    context_window_tokens: int
    remaining_ratio: float
    threshold_ratio: float
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

        used_tokens = max(context.prompt_tokens_estimate, 0)
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
            threshold_ratio=self.threshold_ratio,
        )


@dataclass(slots=True)
class LocalSummaryV1Implementation:
    """Deterministic local summary generation implementation."""

    max_lines: int = 8
    max_line_chars: int = 120
    name: str = DEFAULT_COMPACTION_IMPLEMENTATION

    def summarize(self, request: SummaryRequest) -> SummaryOutput:
        source_items = _summary_source_items(request.items)
        lines: list[str] = []
        for item in source_items[: self.max_lines]:
            lines.append(f"- {_summarize_item(item, max_chars=self.max_line_chars)}")

        remaining = len(source_items) - min(len(source_items), self.max_lines)
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
            prompt_tokens_estimate=_estimate_prompt_tokens(history),
            context_window_tokens=self.context_window_tokens,
        )
        plan = self.strategy.plan(context)
        if plan is None:
            return None

        items_to_replace = history[: plan.replace_end]
        summary_items = _summary_source_items(items_to_replace)
        if len(summary_items) == 0:
            return None
        summary_output = self.implementation.summarize(
            SummaryRequest(items=summary_items, max_chars=self.summary_max_chars)
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
            replaced_items=plan.replace_end,
            estimated_prompt_tokens=plan.used_tokens,
            context_window_tokens=self.context_window_tokens,
            remaining_ratio=plan.remaining_ratio,
            threshold_ratio=plan.threshold_ratio,
            summary_text=summary_text,
        )


def create_compaction_orchestrator(
    *,
    strategy_name: str = DEFAULT_COMPACTION_STRATEGY,
    implementation_name: str = DEFAULT_COMPACTION_IMPLEMENTATION,
    strategy_options: dict[str, object] | None = None,
    implementation_options: dict[str, object] | None = None,
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
        strategy=strategy_factory(strategy_options or {}),
        implementation=implementation_factory(implementation_options or {}),
        context_window_tokens=context_window_tokens,
        summary_max_chars=summary_max_chars,
    )


def _build_threshold_v1_strategy(options: dict[str, object]) -> CompactionStrategy:
    return ThresholdV1Strategy(
        threshold_ratio=_to_float_option(options, "threshold_ratio", 0.2),
        keep_recent_items=_to_int_option(options, "keep_recent_items", 8),
        min_replace_items=_to_int_option(options, "min_replace_items", 2),
    )


def _build_local_summary_v1_implementation(options: dict[str, object]) -> CompactionImplementation:
    return LocalSummaryV1Implementation(
        max_lines=_to_int_option(options, "max_lines", 8),
        max_line_chars=_to_int_option(options, "max_line_chars", 120),
    )


STRATEGY_REGISTRY: dict[str, Callable[[dict[str, object]], CompactionStrategy]] = {
    DEFAULT_COMPACTION_STRATEGY: _build_threshold_v1_strategy,
}
IMPLEMENTATION_REGISTRY: dict[str, Callable[[dict[str, object]], CompactionImplementation]] = {
    DEFAULT_COMPACTION_IMPLEMENTATION: _build_local_summary_v1_implementation,
}


def _render_summary_block(
    *,
    summary: str,
) -> str:
    body = summary.strip() or "No summary content."
    return f"{_SUMMARY_BLOCK_MARKER}\n{body}"


def _summary_source_items(items: list[PromptItem]) -> list[PromptItem]:
    return [item for item in items if not _is_summary_block_item(item)]


def _is_summary_block_item(item: PromptItem) -> bool:
    if item.get("role") != "system":
        return False
    content = item.get("content")
    if not isinstance(content, str):
        return False
    return content.lstrip().startswith(_SUMMARY_BLOCK_MARKER)


def _estimate_prompt_tokens(history: list[PromptItem]) -> int:
    if len(history) == 0:
        return 0
    total_chars = sum(len(str(item)) for item in history)
    if total_chars <= 0:
        return 0
    return max(1, math.ceil(total_chars / _CHARS_PER_TOKEN_ESTIMATE))


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


def _to_int_option(options: dict[str, object], key: str, default: int) -> int:
    value = options.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _to_float_option(options: dict[str, object], key: str, default: float) -> float:
    value = options.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default
