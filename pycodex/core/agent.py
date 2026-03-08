"""Async agent loop orchestration for model sampling and tool execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from inspect import isawaitable
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from pycodex.core.compaction import (
    CompactionApplied,
    SupportsModelComplete,
    create_compaction_orchestrator,
)
from pycodex.core.initial_context import build_initial_context
from pycodex.core.model_client import Completed as ModelCompleted
from pycodex.core.model_client import OutputItemDone, OutputTextDelta
from pycodex.core.rollout_schema import (
    SCHEMA_VERSION,
    HistoryItem,
    SessionMeta,
)
from pycodex.core.rollout_schema import (
    CompactionApplied as RolloutCompactionApplied,
)
from pycodex.core.rollout_schema import (
    TurnCompleted as RolloutTurnCompleted,
)
from pycodex.core.rollout_schema import (
    UsageSnapshot as RolloutUsageSnapshot,
)
from pycodex.core.session import PromptItem, Session, UsageSnapshot
from pycodex.core.skills.injector import SkillInjectedMessage, build_skill_injection_plan
from pycodex.core.skills.manager import SkillRegistry, SkillsManager
from pycodex.core.skills.resolver import SkillMention, extract_skill_mentions
from pycodex.tools.orchestrator import ToolAborted

_log = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class TurnStarted:
    """Event emitted when an agent turn begins."""

    user_input: str
    type: Literal["turn_started"] = "turn_started"


@dataclass(slots=True, frozen=True)
class ToolCallDispatched:
    """Event emitted before a tool call is executed."""

    call_id: str
    name: str
    arguments: str | dict[str, Any]
    type: Literal["tool_call_dispatched"] = "tool_call_dispatched"


@dataclass(slots=True, frozen=True)
class ToolResultReceived:
    """Event emitted after a tool call result is received."""

    call_id: str
    name: str
    result: str
    type: Literal["tool_result_received"] = "tool_result_received"


@dataclass(slots=True, frozen=True)
class TurnCompleted:
    """Event emitted when the turn completes with final text."""

    final_text: str
    usage: UsageSnapshot | None = None
    type: Literal["turn_completed"] = "turn_completed"


@dataclass(slots=True, frozen=True)
class TextDeltaReceived:
    """Event emitted for incremental assistant text output."""

    delta: str
    item_id: str | None = None
    output_index: int | None = None
    type: Literal["text_delta_received"] = "text_delta_received"


@dataclass(slots=True, frozen=True)
class ContextCompacted:
    """Event emitted when context compaction is applied for the active turn."""

    strategy: str
    implementation: str
    replaced_items: int
    estimated_prompt_tokens: int
    context_window_tokens: int
    remaining_ratio: float
    threshold_ratio: float
    type: Literal["context_compacted"] = "context_compacted"


@dataclass(slots=True, frozen=True)
class ContextPressure:
    """Event emitted when context is approaching compaction threshold."""

    remaining_ratio: float
    context_window_tokens: int
    estimated_prompt_tokens: int
    type: Literal["context_pressure"] = "context_pressure"


AgentEvent = (
    TurnStarted
    | ToolCallDispatched
    | ToolResultReceived
    | TurnCompleted
    | TextDeltaReceived
    | ContextCompacted
    | ContextPressure
)
EventCallback = Callable[[AgentEvent], None | Awaitable[None]]


class SupportsModelClient(Protocol):
    """Protocol for model clients that can stream response events."""

    def stream(
        self,
        messages: list[PromptItem],
        tools: list[dict[str, Any]],
        instructions: str = "",
    ) -> AsyncIterator[Any]:
        """Yield streaming model events."""


class SupportsToolRouter(Protocol):
    """Protocol for routing tool calls from model output."""

    def tool_specs(self) -> list[dict[str, Any]]:
        """Return tool specs for model input."""

    async def dispatch(
        self,
        *,
        name: str,
        arguments: str | dict[str, Any],
        cwd: Path,
    ) -> str:
        """Dispatch a tool call to a registered handler."""


class SupportsCompactionOrchestrator(Protocol):
    """Protocol for applying history compaction before model sampling."""

    async def compact(self, session: Session) -> CompactionApplied | None:
        """Compact session history when required."""


@dataclass(slots=True, frozen=True)
class ParsedToolCall:
    """Normalized function-call item extracted from model output."""

    call_id: str
    name: str
    arguments: str | dict[str, Any]


@dataclass(slots=True)
class Agent:
    """Coordinates the model <-> tools loop for a single user turn."""

    session: Session
    model_client: SupportsModelClient
    tool_router: SupportsToolRouter
    cwd: Path
    on_event: EventCallback | None = None
    compaction_orchestrator: SupportsCompactionOrchestrator | None = None
    skills_manager: SkillsManager | None = None
    model_signal_budget: int = 3

    async def run_turn(self, user_input: str) -> str:
        """Run one user turn until the model emits no tool calls."""
        new_initial_items = self._ensure_initial_context()
        await self._persist_session_meta_if_needed()
        if new_initial_items:
            await self._persist_initial_context(new_initial_items)
        _log.debug("turn started: %r", user_input[:80])
        self.session.append_user_message(user_input)
        await self._persist_latest_history_item()
        registry = self._load_skill_registry()
        injected_this_turn: set[str] = set()
        signal_budget = max(self.model_signal_budget, 0)
        signal_iteration = 0
        await self._inject_turn_skill_messages(
            user_input,
            registry=registry,
            injected_out=injected_this_turn,
        )
        await self._emit(TurnStarted(user_input=user_input))
        pending_tool_calls: dict[str, str] = {}
        pressure_emitted = False
        orchestrator = self._resolve_compaction_orchestrator()

        try:
            while True:
                compaction = await self._compact_history_if_needed(orchestrator=orchestrator)
                if compaction is not None:
                    await self._persist_compaction(compaction)
                    await self._emit(
                        ContextCompacted(
                            strategy=compaction.strategy,
                            implementation=compaction.implementation,
                            replaced_items=compaction.replaced_items,
                            estimated_prompt_tokens=compaction.estimated_prompt_tokens,
                            context_window_tokens=compaction.context_window_tokens,
                            remaining_ratio=compaction.remaining_ratio,
                            threshold_ratio=compaction.threshold_ratio,
                        )
                    )
                elif not pressure_emitted:
                    pressure_warning = self._build_context_pressure_warning(
                        orchestrator=orchestrator
                    )
                    if pressure_warning is not None:
                        pressure_emitted = True
                        await self._emit(pressure_warning)
                tool_calls, text, usage = await self._sample_model_once()
                if not tool_calls:
                    if text:
                        self.session.append_assistant_message(text)
                        await self._persist_latest_history_item()
                    signals = self._find_new_skill_signals(
                        text=text,
                        registry=registry,
                        already_injected=injected_this_turn,
                    )
                    if signal_budget > 0 and signals:
                        signal_budget -= 1
                        signal_iteration += 1
                        for mention in signals:
                            _log.info(
                                "skill.model_signal name=%s iteration=%d",
                                mention.name,
                                signal_iteration,
                            )
                        await self._inject_signaled_skills(
                            mentions=signals,
                            registry=registry,
                            injected_out=injected_this_turn,
                        )
                        continue
                    usage_snapshot = self.session.record_turn_usage(usage)
                    self.session.mark_turn_completed()
                    await self._persist_turn_completed(usage_snapshot=usage_snapshot)
                    await self.session.flush_rollout()
                    _log.info("turn completed: %d chars", len(text))
                    await self._emit(TurnCompleted(final_text=text, usage=usage_snapshot))
                    return text

                if text:
                    self.session.append_assistant_message(text)
                    await self._persist_latest_history_item()

                for tool_call in tool_calls:
                    self.session.append_function_call(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        arguments=tool_call.arguments,
                    )
                    await self._persist_latest_history_item()
                    pending_tool_calls[tool_call.call_id] = tool_call.name
                    _log.debug(
                        "dispatching tool %r (call_id=%s) args=%s",
                        tool_call.name,
                        tool_call.call_id,
                        _summarize_args(tool_call.arguments),
                    )
                    await self._emit(
                        ToolCallDispatched(
                            call_id=tool_call.call_id,
                            name=tool_call.name,
                            arguments=tool_call.arguments,
                        )
                    )
                    try:
                        result = await self.tool_router.dispatch(
                            name=tool_call.name,
                            arguments=tool_call.arguments,
                            cwd=self.cwd,
                        )
                    except ToolAborted:
                        # ABORT is terminal for this turn: return immediately
                        # without dispatching additional tool calls.
                        pending_call_ids = _append_pending_tool_outputs(
                            session=self.session,
                            pending_tool_calls=pending_tool_calls,
                            outcome="aborted by user",
                        )
                        await self._persist_pending_tool_outputs(
                            call_ids=pending_call_ids,
                            outcome="aborted by user",
                        )
                        self.session.mark_turn_completed()
                        await self._persist_turn_completed(usage_snapshot=None)
                        await self.session.flush_rollout()
                        abort_text = "Aborted by user."
                        _log.info("turn aborted by user during tool %r", tool_call.name)
                        await self._emit(TurnCompleted(final_text=abort_text))
                        return abort_text
                    except asyncio.CancelledError:
                        pending_call_ids = _append_pending_tool_outputs(
                            session=self.session,
                            pending_tool_calls=pending_tool_calls,
                            outcome="interrupted",
                        )
                        await self._persist_pending_tool_outputs(
                            call_ids=pending_call_ids,
                            outcome="interrupted",
                        )
                        raise
                    pending_tool_calls.pop(tool_call.call_id, None)
                    _log.debug("tool %r result: %d chars", tool_call.name, len(result))
                    self.session.append_tool_result(tool_call.call_id, result)
                    await self._persist_latest_history_item()
                    await self._emit(
                        ToolResultReceived(
                            call_id=tool_call.call_id,
                            name=tool_call.name,
                            result=result,
                        )
                    )
        except asyncio.CancelledError:
            pending_call_ids = _append_pending_tool_outputs(
                session=self.session,
                pending_tool_calls=pending_tool_calls,
                outcome="interrupted",
            )
            await self._persist_pending_tool_outputs(
                call_ids=pending_call_ids,
                outcome="interrupted",
            )
            raise

    async def _sample_model_once(self) -> tuple[list[ParsedToolCall], str, dict[str, int] | None]:
        text_parts: list[str] = []
        tool_calls: list[ParsedToolCall] = []
        usage: dict[str, int] | None = None
        saw_text_delta = False

        async for event in self.model_client.stream(
            messages=self.session.to_prompt(),
            tools=self.tool_router.tool_specs(),
            instructions=self._profile_instructions(),
        ):
            if isinstance(event, OutputTextDelta):
                text_parts.append(event.delta)
                saw_text_delta = True
                await self._emit(
                    TextDeltaReceived(
                        delta=event.delta,
                        item_id=event.item_id,
                        output_index=event.output_index,
                    )
                )
            elif isinstance(event, OutputItemDone):
                parsed = _parse_tool_call_item(item=event.item, ordinal=len(tool_calls) + 1)
                if parsed is not None:
                    tool_calls.append(parsed)
                elif not saw_text_delta:
                    completed_text = _extract_assistant_text_from_item(event.item)
                    if completed_text is not None:
                        text_parts.append(completed_text)
            elif isinstance(event, ModelCompleted):
                usage = event.usage

        return tool_calls, "".join(text_parts), usage

    async def _inject_turn_skill_messages(
        self,
        user_input: str,
        *,
        registry: SkillRegistry | None,
        injected_out: set[str],
    ) -> None:
        existing_keys = self._existing_injected_keys_for_same_turn()
        injected_out.update(name for name, _, _ in existing_keys)
        if "$" not in user_input or registry is None:
            return

        plan = build_skill_injection_plan(user_input=user_input, registry=registry)
        await self._append_injected_messages(
            injected_messages=plan.messages,
            existing_keys=existing_keys,
            injected_out=injected_out,
        )

    async def _append_injected_messages(
        self,
        *,
        injected_messages: tuple[SkillInjectedMessage, ...],
        existing_keys: set[tuple[str, str | None, str | None]],
        injected_out: set[str],
    ) -> None:
        for injected in injected_messages:
            key = (
                injected.name,
                str(injected.path) if injected.path is not None else None,
                injected.reason,
            )
            if key in existing_keys:
                injected_out.add(injected.name)
                _log.debug(
                    "skill.replay_skip name=%s path=%s",
                    injected.name,
                    str(injected.path) if injected.path is not None else "",
                )
                continue
            self.session.append_user_message(
                injected.content,
                skill_injected=True,
                skill_name=injected.name,
                skill_path=str(injected.path) if injected.path is not None else None,
                skill_reason=injected.reason,
            )
            await self._persist_latest_history_item()
            existing_keys.add(key)
            injected_out.add(injected.name)

    async def _inject_signaled_skills(
        self,
        *,
        mentions: list[SkillMention],
        registry: SkillRegistry | None,
        injected_out: set[str],
    ) -> None:
        if registry is None or not mentions:
            return

        existing_keys = self._existing_injected_keys_for_same_turn()
        injected_out.update(name for name, _, _ in existing_keys)
        mention_text = " ".join(f"${mention.name}" for mention in mentions)
        plan = build_skill_injection_plan(user_input=mention_text, registry=registry)
        await self._append_injected_messages(
            injected_messages=plan.messages,
            existing_keys=existing_keys,
            injected_out=injected_out,
        )

    def _find_new_skill_signals(
        self,
        *,
        text: str,
        registry: SkillRegistry | None,
        already_injected: set[str],
    ) -> list[SkillMention]:
        if registry is None or "$" not in text:
            return []
        mentions = extract_skill_mentions(text)
        return [
            mention
            for mention in mentions
            if mention.name not in already_injected
            and not registry.is_model_invocation_disabled(mention.name)
        ]

    def _load_skill_registry(self) -> SkillRegistry | None:
        config = self.session.config
        manager = self.skills_manager or (config.skills_manager if config is not None else None)
        if manager is None:
            manager = SkillsManager()

        skill_dirs = config.skill_dirs if config is not None else ()
        user_root = config.skills_user_root if config is not None else None
        system_root = config.skills_system_root if config is not None else None

        try:
            return manager.get_registry(
                cwd=self.cwd,
                project_skill_dirs=skill_dirs,
                user_root=user_root,
                system_root=system_root,
            )
        except Exception:
            return None

    def _existing_injected_keys_for_same_turn(
        self,
    ) -> set[tuple[str, str | None, str | None]]:
        history = self.session.to_prompt()
        # Need the user message we just appended plus at least one item before it.
        if len(history) < 2:
            return set()

        # Scan backward from second-to-last, collecting consecutive skill_injected
        # items. These represent skills already injected for this turn on a prior
        # attempt (resume case). Stop at the first non-skill-injected item.
        existing: set[tuple[str, str | None, str | None]] = set()
        for item in reversed(history[:-1]):
            if item.get("skill_injected") is not True:
                break
            name = item.get("skill_name")
            if not isinstance(name, str):
                break
            raw_path = item.get("skill_path")
            path = raw_path if isinstance(raw_path, str) else None
            raw_reason = item.get("skill_reason")
            reason = raw_reason if isinstance(raw_reason, str) else None
            existing.add((name, path, reason))
        return existing

    async def _emit(self, event: AgentEvent) -> None:
        if self.on_event is None:
            return
        maybe_awaitable = self.on_event(event)
        if isawaitable(maybe_awaitable):
            await maybe_awaitable

    def _ensure_initial_context(self) -> list[PromptItem]:
        """Inject initial context if not yet done; return newly injected items."""
        if self.session.config is None or self.session.has_initial_context():
            return []
        initial_items = build_initial_context(self.session.config)
        if initial_items:
            self.session.prepend_items(initial_items)
        self.session.mark_initial_context_injected()
        return list(initial_items)

    def _profile_instructions(self) -> str:
        if self.session.config is None:
            return ""
        return self.session.config.profile.instructions

    async def _compact_history_if_needed(
        self,
        *,
        orchestrator: SupportsCompactionOrchestrator | None = None,
    ) -> CompactionApplied | None:
        if orchestrator is None:
            orchestrator = self._resolve_compaction_orchestrator()
        if orchestrator is None:
            return None
        return await orchestrator.compact(self.session)

    def _build_context_pressure_warning(
        self,
        *,
        orchestrator: SupportsCompactionOrchestrator | None,
    ) -> ContextPressure | None:
        if orchestrator is None:
            return None

        threshold_ratio = _compaction_threshold_ratio(orchestrator)
        if threshold_ratio is None:
            return None

        context_window_tokens = _compaction_context_window(orchestrator)
        if context_window_tokens <= 0:
            return None

        estimated_prompt_tokens = _estimate_prompt_tokens_for_session(self.session)
        remaining_tokens = max(context_window_tokens - estimated_prompt_tokens, 0)
        remaining_ratio = remaining_tokens / context_window_tokens
        warning_upper_bound = min(1.0, threshold_ratio * 1.5)
        if remaining_ratio <= threshold_ratio or remaining_ratio > warning_upper_bound:
            return None

        return ContextPressure(
            remaining_ratio=remaining_ratio,
            context_window_tokens=context_window_tokens,
            estimated_prompt_tokens=estimated_prompt_tokens,
        )

    def _resolve_compaction_orchestrator(self) -> SupportsCompactionOrchestrator | None:
        if self.compaction_orchestrator is not None:
            return self.compaction_orchestrator
        config = self.session.config
        if config is None:
            return None
        strategy_options = _compaction_component_options(config.compaction_options, key="strategy")
        implementation_options = _compaction_component_options(
            config.compaction_options, key="implementation"
        )
        implementation_options.setdefault(
            "custom_instructions", config.compaction_custom_instructions
        )
        if "threshold_ratio" not in strategy_options:
            strategy_options["threshold_ratio"] = config.compaction_threshold_ratio
        self.compaction_orchestrator = create_compaction_orchestrator(
            strategy_name=config.compaction_strategy,
            implementation_name=config.compaction_implementation,
            strategy_options=strategy_options,
            implementation_options=implementation_options,
            context_window_tokens=config.compaction_context_window_tokens,
            model_client=cast(SupportsModelComplete | None, self.model_client),
        )
        return self.compaction_orchestrator

    async def _persist_initial_context(self, items: list[PromptItem]) -> None:
        await self.session.record_rollout_items(
            [
                HistoryItem(
                    schema_version=SCHEMA_VERSION,
                    thread_id=self.session.thread_id,
                    item=cast(dict[str, Any], item),
                )
                for item in items
            ]
        )

    async def _persist_session_meta_if_needed(self) -> None:
        recorder = self.session.rollout_recorder()
        if recorder is None or self.session.rollout_meta_written():
            return
        config = self.session.config
        if config is None:
            return

        await recorder.record(
            [
                SessionMeta(
                    schema_version=SCHEMA_VERSION,
                    thread_id=self.session.thread_id,
                    profile=config.profile.name,
                    model=config.model,
                    cwd=str(config.cwd),
                    opened_at=_utc_timestamp(),
                    import_source=None,
                )
            ]
        )
        self.session.mark_rollout_meta_written()

    async def _persist_latest_history_item(self) -> None:
        item = self.session.latest_history_item()
        if item is None:
            return
        await self.session.record_rollout_items(
            [
                HistoryItem(
                    schema_version=SCHEMA_VERSION,
                    thread_id=self.session.thread_id,
                    item=cast(dict[str, Any], item),
                )
            ]
        )

    async def _persist_turn_completed(self, *, usage_snapshot: UsageSnapshot | None) -> None:
        usage_payload = usage_snapshot
        if usage_payload is None:
            usage_payload = {
                "turn": {"input_tokens": 0, "output_tokens": 0},
                "cumulative": self.session.cumulative_usage(),
            }

        await self.session.record_rollout_items(
            [
                RolloutTurnCompleted(
                    schema_version=SCHEMA_VERSION,
                    thread_id=self.session.thread_id,
                    usage=RolloutUsageSnapshot.model_validate(usage_payload),
                )
            ]
        )

    async def _persist_compaction(self, compaction: CompactionApplied) -> None:
        await self.session.record_rollout_items(
            [
                RolloutCompactionApplied(
                    schema_version=SCHEMA_VERSION,
                    thread_id=self.session.thread_id,
                    summary_text=compaction.summary_text,
                    replace_start=compaction.replace_start,
                    replace_end=compaction.replace_end,
                    replaced_items=compaction.replaced_items,
                    strategy=compaction.strategy,
                    implementation=compaction.implementation,
                )
            ]
        )

    async def _persist_pending_tool_outputs(self, *, call_ids: list[str], outcome: str) -> None:
        if len(call_ids) == 0:
            return
        for call_id in call_ids:
            await self.session.record_rollout_items(
                [
                    HistoryItem(
                        schema_version=SCHEMA_VERSION,
                        thread_id=self.session.thread_id,
                        item={"role": "tool", "tool_call_id": call_id, "content": outcome},
                    )
                ]
            )


def _compaction_component_options(
    raw_options: dict[str, dict[str, Any]],
    *,
    key: str,
) -> dict[str, object]:
    component = raw_options.get(key)
    if component is None:
        return {}
    return dict(component)


def _estimate_prompt_tokens_for_session(session: Session) -> int:
    return session.estimated_prompt_tokens()


def _compaction_threshold_ratio(orchestrator: SupportsCompactionOrchestrator) -> float | None:
    strategy = getattr(orchestrator, "strategy", None)
    if strategy is None:
        return None
    raw_threshold = getattr(strategy, "threshold_ratio", None)
    if not isinstance(raw_threshold, (int, float)) or isinstance(raw_threshold, bool):
        return None
    threshold_ratio = float(raw_threshold)
    if threshold_ratio <= 0:
        return None
    return threshold_ratio


def _compaction_context_window(orchestrator: SupportsCompactionOrchestrator) -> int:
    raw_context_window = getattr(orchestrator, "context_window_tokens", 0)
    if isinstance(raw_context_window, bool):
        return 0
    if isinstance(raw_context_window, int):
        return max(raw_context_window, 0)
    if isinstance(raw_context_window, float):
        return max(int(raw_context_window), 0)
    return 0


async def run_turn(
    *,
    session: Session,
    model_client: SupportsModelClient,
    tool_router: SupportsToolRouter,
    cwd: Path,
    user_input: str,
    on_event: EventCallback | None = None,
) -> str:
    """Run one agent turn with explicit dependencies."""
    agent = Agent(
        session=session,
        model_client=model_client,
        tool_router=tool_router,
        cwd=cwd,
        on_event=on_event,
    )
    return await agent.run_turn(user_input)


def _parse_tool_call_item(item: Any, *, ordinal: int) -> ParsedToolCall | None:
    if not isinstance(item, dict):
        return None

    if item.get("type") != "function_call":
        return None

    name = item.get("name")
    if not isinstance(name, str) or not name:
        return None

    arguments = item.get("arguments", "{}")
    if isinstance(arguments, dict):
        normalized_arguments: str | dict[str, Any] = arguments
    elif isinstance(arguments, str):
        normalized_arguments = arguments
    else:
        normalized_arguments = "{}"

    call_id_raw = item.get("call_id", item.get("id"))
    call_id = call_id_raw if isinstance(call_id_raw, str) and call_id_raw else f"call_{ordinal}"

    return ParsedToolCall(
        call_id=call_id,
        name=name,
        arguments=normalized_arguments,
    )


def _extract_assistant_text_from_item(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    if item.get("type") != "message":
        return None
    if item.get("role") != "assistant":
        return None

    content = item.get("content")
    if not isinstance(content, list):
        return None

    text_parts: list[str] = []
    for content_item in content:
        if not isinstance(content_item, dict):
            continue
        if content_item.get("type") != "output_text":
            continue

        text = content_item.get("text")
        if isinstance(text, str):
            text_parts.append(text)

    if not text_parts:
        return None
    return "".join(text_parts)


def _append_pending_tool_outputs(
    *,
    session: Session,
    pending_tool_calls: dict[str, str],
    outcome: str,
) -> list[str]:
    appended_call_ids: list[str] = []
    for call_id in list(pending_tool_calls.keys()):
        session.append_tool_result(call_id, outcome)
        appended_call_ids.append(call_id)
    pending_tool_calls.clear()
    return appended_call_ids


_SUMMARIZE_TRUNCATE = 120  # chars per value before truncating


def _summarize_args(arguments: str | dict[str, Any]) -> str:
    """Return a compact one-line summary of tool arguments for debug logging.

    Long string values are truncated so a write_file call with thousands of
    characters of content doesn't flood the log.
    """
    if isinstance(arguments, str):
        raw = arguments.strip()
        return raw[:_SUMMARIZE_TRUNCATE] + ("…" if len(raw) > _SUMMARIZE_TRUNCATE else "")

    parts: list[str] = []
    for k, v in arguments.items():
        v_str = repr(v)
        if len(v_str) > _SUMMARIZE_TRUNCATE:
            v_str = v_str[:_SUMMARIZE_TRUNCATE] + "…'"
        parts.append(f"{k}={v_str}")
    return "{" + ", ".join(parts) + "}"


def _utc_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
