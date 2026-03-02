from __future__ import annotations

import pytest
from pycodex.core.compaction import (
    CompactionContext,
    CompactionOrchestrator,
    LocalSummaryV1Implementation,
    SummaryRequest,
    ThresholdV1Strategy,
)
from pycodex.core.session import Session


def _build_session_with_messages(pairs: int) -> Session:
    session = Session()
    for index in range(pairs):
        session.append_user_message(f"user-{index}")
        session.append_assistant_message(f"assistant-{index}")
    return session


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
    assert plan.replace_end == 12
    assert plan.used_tokens == 950
    assert plan.remaining_ratio == pytest.approx(0.05)


def test_compaction_orchestrator_replaces_prefix_with_summary_and_keeps_tail() -> None:
    session = _build_session_with_messages(pairs=8)
    history_before = session.to_prompt()
    orchestrator = CompactionOrchestrator(
        strategy=ThresholdV1Strategy(threshold_ratio=0.2, keep_recent_items=4, min_replace_items=2),
        implementation=LocalSummaryV1Implementation(),
        context_window_tokens=20,
        summary_max_chars=500,
    )

    applied = orchestrator.compact(session)

    assert applied is not None
    assert applied.strategy == "threshold_v1"
    assert applied.implementation == "local_summary_v1"
    assert applied.replaced_items == applied.replace_end
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


def test_compaction_orchestrator_is_idempotent_without_new_history() -> None:
    session = _build_session_with_messages(pairs=8)
    orchestrator = CompactionOrchestrator(
        strategy=ThresholdV1Strategy(threshold_ratio=0.2, keep_recent_items=4, min_replace_items=2),
        implementation=LocalSummaryV1Implementation(),
        context_window_tokens=20,
    )

    first = orchestrator.compact(session)
    first_history = session.to_prompt()
    second = orchestrator.compact(session)
    second_history = session.to_prompt()

    assert first is not None
    assert second is None
    assert second_history == first_history


def test_local_summary_v1_is_deterministic_for_same_input() -> None:
    session = _build_session_with_messages(pairs=4)
    items = session.to_prompt()
    implementation = LocalSummaryV1Implementation(max_lines=3, max_line_chars=80)
    request = SummaryRequest(items=items, max_chars=300)

    first = implementation.summarize(request=request)
    second = implementation.summarize(request=request)

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

    summary = implementation.summarize(request=request)

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

    applied = orchestrator.compact(session)

    assert applied is None
    assert session.to_prompt() == history_before
