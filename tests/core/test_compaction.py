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
        cumulative_usage={"input_tokens": 80, "output_tokens": 20},
        context_window_tokens=1000,
    )

    plan = strategy.plan(context)

    assert plan is None


def test_threshold_strategy_returns_plan_when_remaining_ratio_is_low() -> None:
    session = _build_session_with_messages(pairs=8)
    strategy = ThresholdV1Strategy(threshold_ratio=0.2, keep_recent_items=4, min_replace_items=2)
    context = CompactionContext(
        history=session.to_prompt(),
        cumulative_usage={"input_tokens": 950, "output_tokens": 0},
        context_window_tokens=1000,
    )

    plan = strategy.plan(context)

    assert plan is not None
    assert plan.replace_end == 12
    assert plan.used_tokens == 950
    assert plan.remaining_ratio == pytest.approx(0.05)


def test_compaction_orchestrator_replaces_prefix_with_summary_and_keeps_tail() -> None:
    session = _build_session_with_messages(pairs=8)
    session.record_turn_usage({"input_tokens": 950, "output_tokens": 0})
    history_before = session.to_prompt()
    orchestrator = CompactionOrchestrator(
        strategy=ThresholdV1Strategy(threshold_ratio=0.2, keep_recent_items=4, min_replace_items=2),
        implementation=LocalSummaryV1Implementation(),
        context_window_tokens=1000,
        summary_max_chars=500,
    )

    applied = orchestrator.compact(session)

    assert applied is not None
    assert applied.strategy == "threshold_v1"
    assert applied.implementation == "local_summary_v1"
    history_after = session.to_prompt()
    assert len(history_after) == 5
    assert history_after[1:] == history_before[-4:]
    summary_item = history_after[0]
    assert summary_item["role"] == "system"
    assert "[compaction.summary.v1]" in summary_item["content"]
    assert "strategy=" not in summary_item["content"]


def test_compaction_orchestrator_is_idempotent_without_new_history() -> None:
    session = _build_session_with_messages(pairs=8)
    session.record_turn_usage({"input_tokens": 950, "output_tokens": 0})
    orchestrator = CompactionOrchestrator(
        strategy=ThresholdV1Strategy(threshold_ratio=0.2, keep_recent_items=4, min_replace_items=2),
        implementation=LocalSummaryV1Implementation(),
        context_window_tokens=1000,
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
