"""Compaction strategy and implementation interfaces plus default components."""

from __future__ import annotations

import inspect
import json
import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from pycodex.core.session import PromptItem, Session

_log = logging.getLogger(__name__)

DEFAULT_COMPACTION_STRATEGY = "threshold_v1"
LOCAL_SUMMARY_V1_IMPLEMENTATION = "local_summary_v1"
MODEL_SUMMARY_V1_IMPLEMENTATION = "model_summary_v1"
DEFAULT_COMPACTION_IMPLEMENTATION = MODEL_SUMMARY_V1_IMPLEMENTATION
DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
DEFAULT_SUMMARY_MAX_CHARS = 1_200
_CHARS_PER_TOKEN_ESTIMATE = 4

SUMMARY_BLOCK_MARKER = "[compaction.summary.v1]"
_SUMMARY_TOOL_RESULT_MAX_CHARS = 2_000
_SUMMARY_TOOL_ARGS_MAX_CHARS = 500

_SUMMARY_TAG_PATTERN = re.compile(r"<summary>(.*?)</summary>", re.DOTALL | re.IGNORECASE)
_DATA_URL_IMAGE_PATTERN = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]{20,}")
_LONG_BASE64_PATTERN = re.compile(r"(?<!\w)[A-Za-z0-9+/]{200,}={0,2}(?!\w)")


@dataclass(frozen=True, slots=True)
class CompactionContext:
    """Inputs used by a compaction strategy to decide whether to compact."""

    history: list[PromptItem]
    prompt_tokens_estimate: int
    context_window_tokens: int
    api_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    """Decision output from a compaction strategy."""

    replace_start: int
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
    replace_start: int
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

    async def summarize(self, request: SummaryRequest) -> SummaryOutput:
        """Return summary output for the requested prompt items."""


class SupportsModelComplete(Protocol):
    """Protocol for model clients that can produce one full response."""

    async def complete(
        self,
        messages: list[PromptItem],
        *,
        instructions: str = "",
        max_output_tokens: int = 4096,
    ) -> str:
        """Return one full model text response."""


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
        if replace_end <= 0:
            return None

        replace_start = 0
        for index, item in enumerate(context.history):
            if index >= replace_end:
                break
            if is_summary_block_item(item):
                replace_start = index + 1

        compactable_count = replace_end - replace_start
        if compactable_count < self.min_replace_items:
            return None

        return CompactionPlan(
            replace_start=replace_start,
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
    name: str = LOCAL_SUMMARY_V1_IMPLEMENTATION

    async def summarize(self, request: SummaryRequest) -> SummaryOutput:
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
class ModelSummaryV1Implementation:
    """Model-generated semantic summary implementation."""

    model_client: SupportsModelComplete
    custom_instructions: str = ""
    max_output_tokens: int = 4096
    name: str = MODEL_SUMMARY_V1_IMPLEMENTATION

    async def summarize(self, request: SummaryRequest) -> SummaryOutput:
        transcript = _format_transcript_for_summary(request.items)
        prompt = _build_model_summary_prompt(
            transcript=transcript,
            custom_instructions=self.custom_instructions,
        )
        raw = await self.model_client.complete(
            [{"role": "user", "content": prompt}],
            instructions="",
            max_output_tokens=self.max_output_tokens,
        )

        extracted = _extract_summary_block(raw)
        text = extracted if extracted is not None else raw.strip()
        if not text:
            text = "No summary generated."

        if len(text) > request.max_chars:
            text = text[: request.max_chars] + "..."

        return SummaryOutput(text=text)


@dataclass(slots=True)
class CompactionOrchestrator:
    """Apply strategy + implementation to compact session history."""

    strategy: CompactionStrategy
    implementation: CompactionImplementation
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS
    summary_max_chars: int = DEFAULT_SUMMARY_MAX_CHARS

    async def compact(self, session: Session) -> CompactionApplied | None:
        history = session.to_prompt()
        cumulative_usage = session.cumulative_usage()
        api_input_tokens = int(cumulative_usage.get("input_tokens", 0))
        token_estimate = _estimate_prompt_tokens(history)
        context = CompactionContext(
            history=history,
            prompt_tokens_estimate=token_estimate,
            context_window_tokens=self.context_window_tokens,
            api_input_tokens=api_input_tokens,
        )

        plan = self.strategy.plan(context)
        if plan is None:
            return None

        items_to_replace = history[plan.replace_start : plan.replace_end]
        summary_items = _summary_source_items(items_to_replace)
        if len(summary_items) == 0:
            return None

        summary_output = await self.implementation.summarize(
            SummaryRequest(items=summary_items, max_chars=self.summary_max_chars)
        )
        summary_text = _render_summary_block(summary=summary_output.text)
        replaced = session.replace_range_with_system_summary(
            replace_start=plan.replace_start,
            replace_end=plan.replace_end,
            summary_text=summary_text,
        )
        if not replaced:
            return None

        replaced_items = plan.replace_end - plan.replace_start
        return CompactionApplied(
            strategy=self.strategy.name,
            implementation=self.implementation.name,
            replace_start=plan.replace_start,
            replace_end=plan.replace_end,
            replaced_items=replaced_items,
            estimated_prompt_tokens=plan.used_tokens,
            context_window_tokens=self.context_window_tokens,
            remaining_ratio=plan.remaining_ratio,
            threshold_ratio=plan.threshold_ratio,
            summary_text=summary_text,
        )


StrategyFactory: TypeAlias = Callable[[dict[str, object]], CompactionStrategy]
ImplementationFactory: TypeAlias = Callable[
    [dict[str, object], SupportsModelComplete | None],
    CompactionImplementation,
]


def create_compaction_orchestrator(
    *,
    strategy_name: str = DEFAULT_COMPACTION_STRATEGY,
    implementation_name: str = DEFAULT_COMPACTION_IMPLEMENTATION,
    strategy_options: dict[str, object] | None = None,
    implementation_options: dict[str, object] | None = None,
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS,
    summary_max_chars: int = DEFAULT_SUMMARY_MAX_CHARS,
    model_client: SupportsModelComplete | None = None,
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
        implementation=_build_implementation(
            implementation_factory,
            options=implementation_options or {},
            model_client=model_client,
        ),
        context_window_tokens=context_window_tokens,
        summary_max_chars=summary_max_chars,
    )


def _build_threshold_v1_strategy(options: dict[str, object]) -> CompactionStrategy:
    return ThresholdV1Strategy(
        threshold_ratio=_to_float_option(options, "threshold_ratio", 0.2),
        keep_recent_items=_to_int_option(options, "keep_recent_items", 8),
        min_replace_items=_to_int_option(options, "min_replace_items", 2),
    )


def _build_local_summary_v1_implementation(
    options: dict[str, object],
    _model_client: SupportsModelComplete | None,
) -> CompactionImplementation:
    return LocalSummaryV1Implementation(
        max_lines=_to_int_option(options, "max_lines", 8),
        max_line_chars=_to_int_option(options, "max_line_chars", 120),
    )


def _build_model_summary_v1_implementation(
    options: dict[str, object],
    model_client: SupportsModelComplete | None,
) -> CompactionImplementation:
    if model_client is None or not hasattr(model_client, "complete"):
        _log.warning(
            "compaction: model_summary_v1 requested but no model_client available; "
            "falling back to local_summary_v1"
        )
        return LocalSummaryV1Implementation()

    custom_instructions = options.get("custom_instructions", "")
    if not isinstance(custom_instructions, str):
        custom_instructions = ""

    return ModelSummaryV1Implementation(
        model_client=model_client,
        custom_instructions=custom_instructions,
        max_output_tokens=_to_int_option(options, "max_output_tokens", 4096),
    )


STRATEGY_REGISTRY: dict[str, StrategyFactory] = {
    DEFAULT_COMPACTION_STRATEGY: _build_threshold_v1_strategy,
}
IMPLEMENTATION_REGISTRY: dict[str, ImplementationFactory] = {
    LOCAL_SUMMARY_V1_IMPLEMENTATION: _build_local_summary_v1_implementation,
    MODEL_SUMMARY_V1_IMPLEMENTATION: _build_model_summary_v1_implementation,
}


def _build_implementation(
    factory: ImplementationFactory,
    *,
    options: dict[str, object],
    model_client: SupportsModelComplete | None,
) -> CompactionImplementation:
    _POSITIONAL_KINDS = (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    try:
        positional_count = sum(
            1 for p in inspect.signature(factory).parameters.values() if p.kind in _POSITIONAL_KINDS
        )
    except (ValueError, TypeError):
        positional_count = 2
    if positional_count >= 2:
        return factory(options, model_client)
    return factory(options)  # type: ignore[call-arg]


def _build_model_summary_prompt(*, transcript: str, custom_instructions: str) -> str:
    prompt = (
        "Your task is to create a detailed summary of the conversation so far. This summary\n"
        "will replace the compacted history — another model instance will resume the session\n"
        "using only this summary plus recent context.\n"
        "\n"
        "Be thorough with technical details, code patterns, and decisions that are essential\n"
        "for continuing the work without losing context. IMPORTANT: Do NOT use any tools.\n"
        "\n"
        "Your summary MUST include these sections:\n"
        "\n"
        "1. Primary Request and Intent\n"
        "   Capture all of the user's explicit requests and goals in detail.\n"
        "\n"
        "2. Key Technical Concepts\n"
        "   List important technologies, frameworks, and architectural decisions discussed.\n"
        "\n"
        "3. Files and Code Sections\n"
        "   For each file read, edited, or created: what changed and why. Include code\n"
        "   snippets for non-obvious changes.\n"
        "\n"
        "4. Tool Calls and Outcomes\n"
        "   Summarize significant shell commands run, their purpose, and their output\n"
        "   (truncate long outputs to the key result).\n"
        "\n"
        "5. Errors and Fixes\n"
        "   List errors encountered and how they were resolved. Include any user corrections.\n"
        "\n"
        "6. All User Messages\n"
        "   List every user message verbatim (not tool results). Critical for preserving intent.\n"
        "\n"
        "7. Pending Tasks\n"
        "   Any tasks explicitly requested but not yet completed.\n"
        "\n"
        "8. Current Work\n"
        "   Precisely what was being done immediately before this summary. Include filenames\n"
        "   and code snippets.\n"
        "\n"
        "9. Next Step\n"
        "   The single next action to take, directly quoting the most recent user instruction.\n"
        "   Only include if clearly defined — do not invent next steps.\n"
        "\n"
        "Wrap your reasoning in <analysis> tags first. Then output ONLY the summary inside\n"
        "<summary>...</summary> tags."
    )

    trimmed_custom = custom_instructions.strip()
    if trimmed_custom:
        prompt += f"\n\nAdditional instructions:\n{trimmed_custom}"

    prompt += f"\n\nConversation transcript:\n{transcript}"
    return prompt


def _extract_summary_block(raw: str) -> str | None:
    matches = _SUMMARY_TAG_PATTERN.findall(raw)
    if len(matches) == 0:
        return None
    return matches[-1].strip() or None


def _format_transcript_for_summary(items: list[PromptItem]) -> str:
    lines: list[str] = []
    for item in items:
        if is_summary_block_item(item):
            content = str(item.get("content", ""))
            lines.append(f"[Prior compaction summary]\n{content}")
            continue

        item_type = item.get("type")
        role = item.get("role")

        if item_type == "function_call":
            name = str(item.get("name", "unknown"))
            arguments = item.get("arguments", "{}")
            rendered_args = _render_tool_arguments(arguments)
            rendered_args = _truncate(rendered_args, max_chars=_SUMMARY_TOOL_ARGS_MAX_CHARS)
            lines.append(f"Tool call: {name}({rendered_args})")
            continue

        if role == "tool":
            call_id = str(item.get("tool_call_id", ""))
            content = _sanitize_tool_output(str(item.get("content", "")))
            lines.append(f"Tool result [{call_id}]: {content}")
            continue

        if role == "user":
            lines.append(f"User: {item.get('content', '')}")
            continue

        if role == "assistant":
            lines.append(f"Assistant: {item.get('content', '')}")
            continue

    if len(lines) == 0:
        return "No transcript items to summarize."
    return "\n\n".join(lines)


def _render_tool_arguments(arguments: object) -> str:
    if isinstance(arguments, dict):
        return json.dumps(arguments, ensure_ascii=True)
    return str(arguments)


def _sanitize_tool_output(text: str) -> str:
    sanitized = _DATA_URL_IMAGE_PATTERN.sub("[binary data omitted]", text)
    sanitized = _LONG_BASE64_PATTERN.sub("[binary data omitted]", sanitized)
    if len(sanitized) > _SUMMARY_TOOL_RESULT_MAX_CHARS:
        return sanitized[:_SUMMARY_TOOL_RESULT_MAX_CHARS] + "[...truncated]"
    return sanitized


def _render_summary_block(*, summary: str) -> str:
    body = summary.strip() or "No summary content."
    return f"{SUMMARY_BLOCK_MARKER}\n{body}"


def _summary_source_items(items: list[PromptItem]) -> list[PromptItem]:
    return [item for item in items if not is_summary_block_item(item)]


def is_summary_block_item(item: PromptItem) -> bool:
    """Return True if ``item`` is a compaction summary system message."""
    if item.get("role") != "system":
        return False
    content = item.get("content")
    if not isinstance(content, str):
        return False
    return content.lstrip().startswith(SUMMARY_BLOCK_MARKER)


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
