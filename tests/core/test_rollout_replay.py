from __future__ import annotations

import json
from pathlib import Path

import pytest
from pycodex.core.rollout_replay import ReplayState, RolloutReplayError, replay_rollout
from pycodex.core.rollout_schema import (
    SCHEMA_VERSION,
    CompactionApplied,
    HistoryItem,
    SessionClosed,
    SessionMeta,
    TokenUsage,
    TurnCompleted,
    UsageSnapshot,
)


def _write_jsonl(path: Path, records: list[object]) -> None:
    lines = [json.dumps(record, ensure_ascii=True) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_rollout_records() -> list[dict[str, object]]:
    return [
        SessionMeta(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            profile="codex",
            model="gpt-4.1-mini",
            cwd="/tmp/project",
            opened_at="2026-03-02T12:00:00Z",
            import_source=None,
        ).model_dump(mode="json"),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "user", "content": "hello"},
        ).model_dump(mode="json"),
        TurnCompleted(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            usage=UsageSnapshot(
                turn=TokenUsage(input_tokens=4, output_tokens=2),
                cumulative=TokenUsage(input_tokens=4, output_tokens=2),
            ),
        ).model_dump(mode="json"),
        CompactionApplied(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            summary_text="[compaction.summary.v1]\nConversation summary:\n- user: hello",
            replace_start=0,
            replace_end=1,
            replaced_items=1,
            strategy="threshold_v1",
            implementation="local_summary_v1",
            strategy_options={"threshold_ratio": 0.2},
            implementation_options={"max_lines": 8},
        ).model_dump(mode="json"),
        SessionClosed(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            closed_at="2026-03-02T12:01:00Z",
            last_user_message="hello",
            turn_count=1,
            token_total=TokenUsage(input_tokens=4, output_tokens=2),
        ).model_dump(mode="json"),
    ]


def test_replay_rollout_reconstructs_history_and_usage(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    _write_jsonl(path, _build_rollout_records())

    state = replay_rollout(path)

    assert isinstance(state, ReplayState)
    assert state.thread_id == "thread_123"
    assert state.history == [
        {
            "role": "system",
            "content": "[compaction.summary.v1]\nConversation summary:\n- user: hello",
        }
    ]
    assert state.cumulative_usage == {"input_tokens": 4, "output_tokens": 2}
    assert state.status == "closed"
    assert state.warnings == []


def test_replay_rollout_skips_unknown_record_types_with_warning(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    records = _build_rollout_records()
    records.insert(
        2,
        {
            "schema_version": SCHEMA_VERSION,
            "type": "future.record",
            "thread_id": "thread_123",
            "value": "x",
        },
    )
    _write_jsonl(path, records)

    state = replay_rollout(path)

    assert len(state.warnings) == 1
    assert "future.record" in state.warnings[0]
    assert state.status == "closed"


def test_replay_rollout_hard_fails_major_schema_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    records = _build_rollout_records()
    records[0]["schema_version"] = "2.0"
    _write_jsonl(path, records)

    with pytest.raises(RolloutReplayError) as exc_info:
        replay_rollout(path)

    assert exc_info.value.code == "schema_version_mismatch"


def test_replay_rollout_tolerates_truncated_final_line(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    records = _build_rollout_records()
    lines = [json.dumps(record, ensure_ascii=True) for record in records]
    path.write_text("\n".join(lines[:-1]) + "\n" + '{"schema_version":"1.0"', encoding="utf-8")

    state = replay_rollout(path)

    assert state.status == "incomplete"
    assert "truncated final JSONL line" in state.warnings[0]


def test_replay_rollout_marks_incomplete_when_session_closed_absent(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    records = _build_rollout_records()[:-1]
    _write_jsonl(path, records)

    state = replay_rollout(path)

    assert state.status == "incomplete"
    assert state.session_closed is None


def test_replay_rollout_returns_not_found_error_when_missing_path(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"

    with pytest.raises(RolloutReplayError) as exc_info:
        replay_rollout(path)

    assert exc_info.value.code == "rollout_not_found"


def test_replay_rollout_skips_malformed_history_item_with_warning(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    records = _build_rollout_records()
    records.insert(
        1,
        {
            "schema_version": SCHEMA_VERSION,
            "type": "history.item",
            "thread_id": "thread_123",
            "item": {"garbage": True},
        },
    )
    _write_jsonl(path, records)

    state = replay_rollout(path)

    assert any("malformed history item" in warning for warning in state.warnings)
    assert all("garbage" not in str(history_item) for history_item in state.history)


def test_replay_rollout_applies_partial_compaction_and_preserves_prefix(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    records = [
        SessionMeta(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            profile="codex",
            model="gpt-4.1-mini",
            cwd="/tmp/project",
            opened_at="2026-03-02T12:00:00Z",
            import_source=None,
        ).model_dump(mode="json"),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "system", "content": "[compaction.summary.v1]\nold"},
        ).model_dump(mode="json"),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "user", "content": "u1"},
        ).model_dump(mode="json"),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "assistant", "content": "a1"},
        ).model_dump(mode="json"),
        CompactionApplied(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            summary_text="[compaction.summary.v1]\nnew",
            replace_start=1,
            replace_end=3,
            replaced_items=2,
            strategy="threshold_v1",
            implementation="local_summary_v1",
            strategy_options={},
            implementation_options={},
        ).model_dump(mode="json"),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "user", "content": "after"},
        ).model_dump(mode="json"),
    ]
    _write_jsonl(path, records)

    state = replay_rollout(path)

    assert state.history == [
        {"role": "system", "content": "[compaction.summary.v1]\nold"},
        {"role": "system", "content": "[compaction.summary.v1]\nnew"},
        {"role": "user", "content": "after"},
    ]
    assert state.warnings == []


def test_replay_rollout_clamps_replace_end_and_emits_warning(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    records = [
        SessionMeta(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            profile="codex",
            model="gpt-4.1-mini",
            cwd="/tmp/project",
            opened_at="2026-03-02T12:00:00Z",
            import_source=None,
        ).model_dump(mode="json"),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "user", "content": "u1"},
        ).model_dump(mode="json"),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "assistant", "content": "a1"},
        ).model_dump(mode="json"),
        CompactionApplied(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            summary_text="[compaction.summary.v1]\nclamped",
            replace_start=1,
            replace_end=99,
            replaced_items=98,
            strategy="threshold_v1",
            implementation="local_summary_v1",
            strategy_options={},
            implementation_options={},
        ).model_dump(mode="json"),
    ]
    _write_jsonl(path, records)

    state = replay_rollout(path)

    assert state.history == [
        {"role": "user", "content": "u1"},
        {"role": "system", "content": "[compaction.summary.v1]\nclamped"},
    ]
    assert any("clamped" in warning for warning in state.warnings)


def test_replay_rollout_applies_consecutive_compactions(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    records = [
        SessionMeta(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            profile="codex",
            model="gpt-4.1-mini",
            cwd="/tmp/project",
            opened_at="2026-03-02T12:00:00Z",
            import_source=None,
        ).model_dump(mode="json"),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "user", "content": "u1"},
        ).model_dump(mode="json"),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "assistant", "content": "a1"},
        ).model_dump(mode="json"),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "user", "content": "u2"},
        ).model_dump(mode="json"),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "assistant", "content": "a2"},
        ).model_dump(mode="json"),
        CompactionApplied(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            summary_text="[compaction.summary.v1]\nfirst",
            replace_start=0,
            replace_end=2,
            replaced_items=2,
            strategy="threshold_v1",
            implementation="local_summary_v1",
            strategy_options={},
            implementation_options={},
        ).model_dump(mode="json"),
        CompactionApplied(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            summary_text="[compaction.summary.v1]\nsecond",
            replace_start=1,
            replace_end=3,
            replaced_items=2,
            strategy="threshold_v1",
            implementation="local_summary_v1",
            strategy_options={},
            implementation_options={},
        ).model_dump(mode="json"),
    ]
    _write_jsonl(path, records)

    state = replay_rollout(path)

    assert state.history == [
        {"role": "system", "content": "[compaction.summary.v1]\nfirst"},
        {"role": "system", "content": "[compaction.summary.v1]\nsecond"},
    ]
