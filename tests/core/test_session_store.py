from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pycodex.core.session_store as session_store
import pytest
from pycodex.core.config import Config
from pycodex.core.rollout_replay import RolloutReplayError
from pycodex.core.rollout_schema import (
    SCHEMA_VERSION,
    HistoryItem,
    SessionClosed,
    SessionMeta,
    TokenUsage,
    TurnCompleted,
    UsageSnapshot,
)


def _config(tmp_path: Path) -> Config:
    return Config(model="test-model", api_key="test-key", cwd=tmp_path)


def _session_meta(thread_id: str) -> SessionMeta:
    return SessionMeta(
        schema_version=SCHEMA_VERSION,
        thread_id=thread_id,
        profile="test",
        model="test-model",
        cwd="/workspace",
        opened_at="2026-01-01T00:00:00Z",
    )


def _session_closed(
    *,
    thread_id: str,
    turn_count: int,
    input_tokens: int,
    output_tokens: int,
    last_user_message: str | None,
) -> SessionClosed:
    return SessionClosed(
        schema_version=SCHEMA_VERSION,
        thread_id=thread_id,
        closed_at="2026-01-01T00:01:00Z",
        last_user_message=last_user_message,
        turn_count=turn_count,
        token_total=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _incomplete_items(
    *,
    thread_id: str,
    message: str,
    input_tokens: int,
    output_tokens: int,
) -> list[Any]:
    return [
        _session_meta(thread_id),
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id=thread_id,
            item={"role": "user", "content": message},
        ),
        TurnCompleted(
            schema_version=SCHEMA_VERSION,
            thread_id=thread_id,
            usage=UsageSnapshot(
                turn=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
                cumulative=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
            ),
        ),
    ]


def _write_rollout(path: Path, items: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(item.model_dump_json() for item in items) + "\n", encoding="utf-8")


def test_list_sessions_uncapped_returns_newest_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_store, "resolve_sessions_root", lambda _config: tmp_path)
    _write_rollout(
        tmp_path / "rollout-20260101-000000000000-thread-old.jsonl",
        [
            _session_meta("thread-old"),
            _session_closed(
                thread_id="thread-old",
                turn_count=1,
                input_tokens=2,
                output_tokens=3,
                last_user_message="old",
            ),
        ],
    )
    _write_rollout(
        tmp_path / "rollout-20260103-000000000000-thread-new.jsonl",
        [
            _session_meta("thread-new"),
            _session_closed(
                thread_id="thread-new",
                turn_count=4,
                input_tokens=5,
                output_tokens=7,
                last_user_message="new",
            ),
        ],
    )
    _write_rollout(
        tmp_path / "rollout-20260102-000000000000-thread-mid.jsonl",
        _incomplete_items(
            thread_id="thread-mid",
            message="mid",
            input_tokens=11,
            output_tokens=13,
        ),
    )

    records = session_store.list_sessions(config=_config(tmp_path), limit=None)

    assert [record.thread_id for record in records] == ["thread-new", "thread-mid", "thread-old"]
    assert [record.status for record in records] == ["closed", "incomplete", "closed"]
    assert records[0].updated_at == "2026-01-01T00:01:00Z"
    assert records[0].size_bytes > 0


def test_list_sessions_respects_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_store, "resolve_sessions_root", lambda _config: tmp_path)
    _write_rollout(
        tmp_path / "rollout-20260102-000000000000-thread-a.jsonl",
        [
            _session_meta("thread-a"),
            _session_closed(
                thread_id="thread-a",
                turn_count=1,
                input_tokens=1,
                output_tokens=1,
                last_user_message=None,
            ),
        ],
    )
    _write_rollout(
        tmp_path / "rollout-20260103-000000000000-thread-b.jsonl",
        [
            _session_meta("thread-b"),
            _session_closed(
                thread_id="thread-b",
                turn_count=2,
                input_tokens=2,
                output_tokens=2,
                last_user_message=None,
            ),
        ],
    )
    _write_rollout(
        tmp_path / "rollout-20260104-000000000000-thread-c.jsonl",
        [
            _session_meta("thread-c"),
            _session_closed(
                thread_id="thread-c",
                turn_count=3,
                input_tokens=3,
                output_tokens=3,
                last_user_message=None,
            ),
        ],
    )

    records = session_store.list_sessions(config=_config(tmp_path), limit=2)

    assert len(records) == 2
    assert [record.thread_id for record in records] == ["thread-c", "thread-b"]


def test_list_sessions_uses_file_metadata_for_incomplete_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_store, "resolve_sessions_root", lambda _config: tmp_path)
    path = tmp_path / "rollout-20260102-000000000000-thread-incomplete.jsonl"
    _write_rollout(
        path,
        _incomplete_items(
            thread_id="thread-incomplete",
            message="incomplete",
            input_tokens=10,
            output_tokens=5,
        ),
    )
    os.utime(path, (1735689600, 1735689600))  # 2025-01-01T00:00:00Z

    records = session_store.list_sessions(config=_config(tmp_path), limit=None)

    assert len(records) == 1
    assert records[0].updated_at == "2025-01-01T00:00:00Z"
    assert records[0].size_bytes == path.stat().st_size


def test_list_sessions_falls_back_to_stat_time_when_closed_at_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_store, "resolve_sessions_root", lambda _config: tmp_path)
    path = tmp_path / "rollout-20260102-000000000000-thread-closed.jsonl"
    path.write_text("{}", encoding="utf-8")
    os.utime(path, (1735689600, 1735689600))  # 2025-01-01T00:00:00Z

    class _FakeClosed:
        thread_id = "thread-closed"
        turn_count = 1
        last_user_message = "hello"
        closed_at = ""
        token_total = TokenUsage(input_tokens=1, output_tokens=2)

    monkeypatch.setattr(session_store, "read_session_closed", lambda _path: _FakeClosed())

    records = session_store.list_sessions(config=_config(tmp_path), limit=None)

    assert len(records) == 1
    assert records[0].updated_at == "2025-01-01T00:00:00Z"


def test_list_sessions_uses_fast_path_for_closed_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_store, "resolve_sessions_root", lambda _config: tmp_path)
    closed_path = tmp_path / "rollout-20260102-000000000000-thread-closed.jsonl"
    incomplete_path = tmp_path / "rollout-20260101-000000000000-thread-incomplete.jsonl"
    _write_rollout(
        closed_path,
        [
            _session_meta("thread-closed"),
            _session_closed(
                thread_id="thread-closed",
                turn_count=9,
                input_tokens=20,
                output_tokens=30,
                last_user_message="closed",
            ),
        ],
    )
    _write_rollout(
        incomplete_path,
        _incomplete_items(
            thread_id="thread-incomplete",
            message="incomplete",
            input_tokens=10,
            output_tokens=5,
        ),
    )

    replay_calls: list[str] = []
    original_replay_rollout = session_store.replay_rollout

    def _recording_replay(path: Path):
        replay_calls.append(path.name)
        return original_replay_rollout(path)

    monkeypatch.setattr(session_store, "replay_rollout", _recording_replay)

    records = session_store.list_sessions(config=_config(tmp_path), limit=None)

    assert len(records) == 2
    assert replay_calls == [incomplete_path.name]


def test_read_session_closed_valid(tmp_path: Path) -> None:
    path = tmp_path / "rollout-20260101-000000000000-thread.jsonl"
    _write_rollout(
        path,
        [
            _session_meta("thread"),
            _session_closed(
                thread_id="thread",
                turn_count=3,
                input_tokens=7,
                output_tokens=11,
                last_user_message="hello",
            ),
        ],
    )

    record = session_store.read_session_closed(path)

    assert record is not None
    assert record.thread_id == "thread"
    assert record.turn_count == 3
    assert record.token_total.input_tokens == 7
    assert record.token_total.output_tokens == 11


def test_read_session_closed_returns_none_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    assert session_store.read_session_closed(path) is None


def test_read_session_closed_returns_none_for_truncated_last_line(tmp_path: Path) -> None:
    path = tmp_path / "truncated.jsonl"
    path.write_text('{"type":"session.closed","schema_version":"1.0"', encoding="utf-8")
    assert session_store.read_session_closed(path) is None


def test_read_session_closed_returns_none_for_non_closed_last_line(tmp_path: Path) -> None:
    path = tmp_path / "non-closed.jsonl"
    _write_rollout(
        path,
        _incomplete_items(
            thread_id="thread-open",
            message="hello",
            input_tokens=1,
            output_tokens=2,
        ),
    )
    assert session_store.read_session_closed(path) is None


def test_resolve_resume_rollout_path_resolves_by_thread_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_store, "resolve_sessions_root", lambda _config: tmp_path)
    older = tmp_path / "rollout-20260101-000000000000-thread-id.jsonl"
    newer = tmp_path / "rollout-20260102-000000000000-thread-id.jsonl"
    _write_rollout(older, [_session_meta("thread-id")])
    _write_rollout(newer, [_session_meta("thread-id")])

    resolved = asyncio.run(
        session_store.resolve_resume_rollout_path(config=_config(tmp_path), resume="thread-id")
    )

    assert resolved == newer


def test_resolve_resume_rollout_path_resolves_explicit_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_store, "resolve_sessions_root", lambda _config: tmp_path)
    path = tmp_path / "rollout-20260101-000000000000-explicit.jsonl"
    _write_rollout(path, [_session_meta("explicit")])

    resolved = asyncio.run(
        session_store.resolve_resume_rollout_path(config=_config(tmp_path), resume=str(path))
    )

    assert resolved == path


def test_resolve_resume_rollout_path_raises_when_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_store, "resolve_sessions_root", lambda _config: tmp_path)

    with pytest.raises(RolloutReplayError, match="Unable to resolve rollout"):
        asyncio.run(
            session_store.resolve_resume_rollout_path(
                config=_config(tmp_path),
                resume="missing-thread",
            )
        )
