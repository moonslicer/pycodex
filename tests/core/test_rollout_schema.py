from __future__ import annotations

import json
from pathlib import Path

import pytest
from pycodex.core.rollout_schema import (
    SCHEMA_VERSION,
    CompactionApplied,
    HistoryItem,
    SessionClosed,
    SessionMeta,
    TokenUsage,
    TurnCompleted,
    UsageSnapshot,
    validate_rollout_item,
)
from pydantic import ValidationError

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "rollout_schema"


def _fixture_text(name: str) -> str:
    return (_FIXTURES_DIR / name).read_text(encoding="utf-8").strip()


def test_session_meta_matches_golden_fixture() -> None:
    item = SessionMeta(
        schema_version=SCHEMA_VERSION,
        thread_id="thread_123",
        profile="codex",
        model="gpt-4.1-mini",
        cwd="/tmp/project",
        opened_at="2026-03-02T10:00:00Z",
        import_source=None,
    )

    assert item.model_dump_json() == _fixture_text("session.meta.json")


def test_history_item_matches_golden_fixture() -> None:
    item = HistoryItem(
        schema_version=SCHEMA_VERSION,
        thread_id="thread_123",
        item={"role": "user", "content": "hello"},
    )

    assert item.model_dump_json() == _fixture_text("history.item.json")


def test_turn_completed_matches_golden_fixture() -> None:
    item = TurnCompleted(
        schema_version=SCHEMA_VERSION,
        thread_id="thread_123",
        usage=UsageSnapshot(
            turn=TokenUsage(input_tokens=10, output_tokens=4),
            cumulative=TokenUsage(input_tokens=25, output_tokens=9),
        ),
    )

    assert item.model_dump_json() == _fixture_text("turn.completed.json")


def test_compaction_applied_matches_golden_fixture() -> None:
    item = CompactionApplied(
        schema_version=SCHEMA_VERSION,
        thread_id="thread_123",
        summary_text="[compaction.summary.v1]\nConversation summary:\n- user: hello",
        replace_end=8,
        replaced_items=8,
        strategy="threshold_v1",
        implementation="local_summary_v1",
        strategy_options={"threshold_ratio": 0.2},
        implementation_options={"max_lines": 8},
    )

    assert item.model_dump_json() == _fixture_text("compaction.applied.json")


def test_session_closed_matches_golden_fixture() -> None:
    item = SessionClosed(
        schema_version=SCHEMA_VERSION,
        thread_id="thread_123",
        closed_at="2026-03-02T10:10:00Z",
        last_user_message="please summarize",
        turn_count=3,
        token_total=TokenUsage(input_tokens=100, output_tokens=40),
    )

    assert item.model_dump_json() == _fixture_text("session.closed.json")


def test_validate_rollout_item_parses_each_required_record_type() -> None:
    record_files = [
        "session.meta.json",
        "history.item.json",
        "turn.completed.json",
        "compaction.applied.json",
        "session.closed.json",
    ]

    for filename in record_files:
        parsed = validate_rollout_item(json.loads(_fixture_text(filename)))
        assert parsed.schema_version == SCHEMA_VERSION


def test_validate_rollout_item_rejects_unknown_type() -> None:
    unknown = {
        "schema_version": SCHEMA_VERSION,
        "type": "unknown.type",
        "thread_id": "thread_123",
    }

    with pytest.raises(ValidationError):
        validate_rollout_item(unknown)


def test_validate_rollout_item_requires_schema_version() -> None:
    item = {
        "type": "session.meta",
        "thread_id": "thread_123",
        "profile": "codex",
        "model": "gpt-4.1-mini",
        "cwd": "/tmp/project",
        "opened_at": "2026-03-02T10:00:00Z",
    }

    with pytest.raises(ValidationError):
        validate_rollout_item(item)


def test_session_meta_accepts_valid_iso_timestamp() -> None:
    item = SessionMeta(
        schema_version=SCHEMA_VERSION,
        thread_id="thread_123",
        profile="codex",
        model="gpt-4.1-mini",
        cwd="/tmp/project",
        opened_at="2026-03-05T14:30:22Z",
    )
    assert item.opened_at == "2026-03-05T14:30:22Z"


def test_session_meta_rejects_invalid_opened_at() -> None:
    with pytest.raises(ValidationError, match="opened_at"):
        SessionMeta(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            profile="codex",
            model="gpt-4.1-mini",
            cwd="/tmp/project",
            opened_at="not-a-date",
        )


def test_session_closed_rejects_invalid_closed_at() -> None:
    with pytest.raises(ValidationError, match="closed_at"):
        SessionClosed(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            closed_at="not-a-date",
            turn_count=1,
            token_total=TokenUsage(input_tokens=10, output_tokens=4),
        )
