from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from pycodex.core.compaction import (
    CompactionContext,
    CompactionOrchestrator,
    LocalSummaryV1Implementation,
    ModelSummaryV1Implementation,
    SummaryRequest,
    ThresholdV1Strategy,
    create_compaction_orchestrator,
)
from pycodex.core.session import Session


def _build_session_with_messages(pairs: int) -> Session:
    session = Session()
    for index in range(pairs):
        session.append_user_message(f"user-{index}")
        session.append_assistant_message(f"assistant-{index}")
    return session


@dataclass(slots=True)
class _FakeModelCompleteClient:
    responses: list[str]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        instructions: str = "",
        max_output_tokens: int = 4096,
    ) -> str:
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "instructions": instructions,
                "max_output_tokens": max_output_tokens,
            }
        )
        if len(self.responses) == 0:
            raise AssertionError("No fake response configured")
        return self.responses.pop(0)


def test_threshold_strategy_skips_when_remaining_ratio_is_high() -> None:
    session = _build_session_with_messages(pairs=6)
    strategy = ThresholdV1Strategy(threshold_ratio=0.2, keep_recent_items=4, min_replace_items=2)
    context = CompactionContext(
        history=session.to_prompt(),
        prompt_tokens_estimate=100,
        context_window_tokens=1000,
    )

    plan = strategy.plan(context)

    assert plan is None


def test_threshold_strategy_returns_plan_when_remaining_ratio_is_low() -> None:
    session = _build_session_with_messages(pairs=8)
    strategy = ThresholdV1Strategy(threshold_ratio=0.2, keep_recent_items=4, min_replace_items=2)
    context = CompactionContext(
        history=session.to_prompt(),
        prompt_tokens_estimate=950,
        context_window_tokens=1000,
    )

    plan = strategy.plan(context)

    assert plan is not None
    assert plan.replace_start == 0
    assert plan.replace_end == 12
    assert plan.used_tokens == 950
    assert plan.remaining_ratio == pytest.approx(0.05)


def test_threshold_strategy_uses_last_summary_boundary_for_replace_start() -> None:
    session = Session()
    session.append_system_message("[compaction.summary.v1]\nConversation summary:\n- old")
    for index in range(5):
        session.append_user_message(f"u-{index}")
        session.append_assistant_message(f"a-{index}")

    strategy = ThresholdV1Strategy(threshold_ratio=0.3, keep_recent_items=2, min_replace_items=2)
    context = CompactionContext(
        history=session.to_prompt(),
        prompt_tokens_estimate=950,
        context_window_tokens=1000,
    )

    plan = strategy.plan(context)

    assert plan is not None
    assert plan.replace_start == 1
    assert plan.replace_end == len(session.to_prompt()) - 2


def test_threshold_strategy_skips_when_new_content_since_last_summary_is_too_small() -> None:
    session = Session()
    session.append_system_message("[compaction.summary.v1]\nConversation summary:\n- old")
    session.append_user_message("u")
    session.append_assistant_message("a")

    strategy = ThresholdV1Strategy(threshold_ratio=0.9, keep_recent_items=2, min_replace_items=1)
    context = CompactionContext(
        history=session.to_prompt(),
        prompt_tokens_estimate=950,
        context_window_tokens=1000,
    )

    plan = strategy.plan(context)

    assert plan is None


def test_compaction_orchestrator_replaces_prefix_with_summary_and_keeps_tail() -> None:
    session = _build_session_with_messages(pairs=8)
    history_before = session.to_prompt()
    orchestrator = CompactionOrchestrator(
        strategy=ThresholdV1Strategy(threshold_ratio=0.2, keep_recent_items=4, min_replace_items=2),
        implementation=LocalSummaryV1Implementation(),
        context_window_tokens=20,
        summary_max_chars=500,
    )

    applied = asyncio.run(orchestrator.compact(session))

    assert applied is not None
    assert applied.strategy == "threshold_v1"
    assert applied.implementation == "local_summary_v1"
    assert applied.replace_start == 0
    assert applied.replaced_items == applied.replace_end - applied.replace_start
    assert applied.context_window_tokens == 20
    assert applied.estimated_prompt_tokens > 0
    assert applied.threshold_ratio == 0.2
    history_after = session.to_prompt()
    assert len(history_after) == 5
    assert history_after[1:] == history_before[-4:]
    summary_item = history_after[0]
    assert summary_item["role"] == "system"
    assert "[compaction.summary.v1]" in summary_item["content"]
    assert "strategy=" not in summary_item["content"]


def test_compaction_orchestrator_uses_replace_boundary_on_second_compaction() -> None:
    session = _build_session_with_messages(pairs=6)
    orchestrator = CompactionOrchestrator(
        strategy=ThresholdV1Strategy(threshold_ratio=0.2, keep_recent_items=2, min_replace_items=2),
        implementation=LocalSummaryV1Implementation(),
        context_window_tokens=20,
    )

    first = asyncio.run(orchestrator.compact(session))
    assert first is not None
    first_history = session.to_prompt()
    prior_summary = first_history[0]

    for index in range(4):
        session.append_user_message(f"new-u-{index}")
        session.append_assistant_message(f"new-a-{index}")

    second = asyncio.run(orchestrator.compact(session))

    assert second is not None
    assert second.replace_start == 1
    history_after_second = session.to_prompt()
    assert history_after_second[0] == prior_summary
    assert history_after_second[1]["role"] == "system"
    assert "[compaction.summary.v1]" in history_after_second[1]["content"]


def test_compaction_orchestrator_is_idempotent_without_new_history() -> None:
    session = _build_session_with_messages(pairs=8)
    orchestrator = CompactionOrchestrator(
        strategy=ThresholdV1Strategy(threshold_ratio=0.2, keep_recent_items=4, min_replace_items=2),
        implementation=LocalSummaryV1Implementation(),
        context_window_tokens=20,
    )

    first = asyncio.run(orchestrator.compact(session))
    first_history = session.to_prompt()
    second = asyncio.run(orchestrator.compact(session))
    second_history = session.to_prompt()

    assert first is not None
    assert second is None
    assert second_history == first_history


def test_local_summary_v1_is_deterministic_for_same_input() -> None:
    session = _build_session_with_messages(pairs=4)
    items = session.to_prompt()
    implementation = LocalSummaryV1Implementation(max_lines=3, max_line_chars=80)
    request = SummaryRequest(items=items, max_chars=300)

    first = asyncio.run(implementation.summarize(request=request))
    second = asyncio.run(implementation.summarize(request=request))

    assert first == second


def test_local_summary_v1_skips_existing_summary_blocks() -> None:
    implementation = LocalSummaryV1Implementation(max_lines=3, max_line_chars=80)
    request = SummaryRequest(
        items=[
            {
                "role": "system",
                "content": "[compaction.summary.v1]\nConversation summary:\n- user: old context",
            },
            {"role": "user", "content": "new question"},
        ],
        max_chars=300,
    )

    summary = asyncio.run(implementation.summarize(request=request))

    assert "[compaction.summary.v1]" not in summary.text
    assert "user: new question" in summary.text


def test_compaction_orchestrator_skips_summary_only_prefix() -> None:
    session = Session()
    session.append_system_message("[compaction.summary.v1]\nConversation summary:\n- user: old")
    session.append_user_message("latest")
    session.append_assistant_message("reply")
    history_before = session.to_prompt()
    orchestrator = CompactionOrchestrator(
        strategy=ThresholdV1Strategy(threshold_ratio=0.9, keep_recent_items=2, min_replace_items=1),
        implementation=LocalSummaryV1Implementation(),
        context_window_tokens=3,
    )

    applied = asyncio.run(orchestrator.compact(session))

    assert applied is None
    assert session.to_prompt() == history_before


def test_model_summary_v1_extracts_summary_and_formats_transcript() -> None:
    fake_client = _FakeModelCompleteClient(
        responses=["<analysis>thinking</analysis>\n<summary>Test summary.</summary>"]
    )
    implementation = ModelSummaryV1Implementation(
        model_client=fake_client,
        custom_instructions="Focus on Python changes.",
        max_output_tokens=222,
    )
    request = SummaryRequest(
        items=[
            {"role": "system", "content": "normal system message"},
            {"role": "user", "content": "User question"},
            {"role": "assistant", "content": "Assistant answer"},
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "read_file",
                "arguments": '{"file_path":"README.md"}',
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "data:image/png;base64,AAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            },
            {
                "role": "system",
                "content": "[compaction.summary.v1]\nConversation summary:\n- previous",
            },
        ],
        max_chars=500,
    )

    summary = asyncio.run(implementation.summarize(request))

    assert summary.text == "Test summary."
    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["instructions"] == ""
    assert fake_client.calls[0]["max_output_tokens"] == 222
    prompt = str(fake_client.calls[0]["messages"][0]["content"])
    assert "User: User question" in prompt
    assert "Assistant: Assistant answer" in prompt
    assert "Tool call: read_file" in prompt
    assert "Tool result [call_1]: [binary data omitted]" in prompt
    assert "[Prior compaction summary]" in prompt
    assert "normal system message" not in prompt
    assert "Focus on Python changes." in prompt


def test_model_summary_v1_falls_back_to_raw_text_when_summary_tags_missing() -> None:
    fake_client = _FakeModelCompleteClient(responses=["Raw summary text"])
    implementation = ModelSummaryV1Implementation(model_client=fake_client)
    request = SummaryRequest(items=[{"role": "user", "content": "hello"}], max_chars=200)

    summary = asyncio.run(implementation.summarize(request))

    assert summary.text == "Raw summary text"


def test_model_summary_v1_applies_max_chars_truncation() -> None:
    fake_client = _FakeModelCompleteClient(
        responses=["<summary>abcdefghijklmnopqrstuvwxyz</summary>"]
    )
    implementation = ModelSummaryV1Implementation(model_client=fake_client)
    request = SummaryRequest(items=[{"role": "user", "content": "hello"}], max_chars=10)

    summary = asyncio.run(implementation.summarize(request))

    assert summary.text == "abcdefghij..."


def test_model_summary_v1_orchestrator_integration() -> None:
    session = _build_session_with_messages(pairs=6)
    fake_client = _FakeModelCompleteClient(responses=["<summary>semantic summary</summary>"])
    orchestrator = create_compaction_orchestrator(
        implementation_name="model_summary_v1",
        strategy_options={"threshold_ratio": 0.2, "keep_recent_items": 2, "min_replace_items": 2},
        context_window_tokens=20,
        model_client=fake_client,
    )

    applied = asyncio.run(orchestrator.compact(session))

    assert applied is not None
    assert applied.implementation == "model_summary_v1"
    assert applied.replace_start == 0
    assert len(fake_client.calls) == 1
