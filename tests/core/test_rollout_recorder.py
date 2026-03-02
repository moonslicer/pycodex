from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pycodex.core.rollout_recorder import (
    RolloutRecorder,
    build_rollout_path,
    resolve_latest_rollout,
    sanitize_thread_id,
)
from pycodex.core.rollout_schema import SCHEMA_VERSION, HistoryItem, SessionMeta


def test_build_rollout_path_uses_flat_layout() -> None:
    root = Path("/tmp/sessions")
    path = build_rollout_path(
        "thread:123",
        now=datetime(2026, 3, 2, 12, 1, 5, 120000, tzinfo=UTC),
        root=root,
    )

    assert path.parent == root
    assert path.name == "rollout-20260302-120105120000-thread_123.jsonl"


def test_resolve_latest_rollout_returns_newest_sorted_filename(tmp_path: Path) -> None:
    old_path = tmp_path / "rollout-20260302-120105120000-thread_123.jsonl"
    new_path = tmp_path / "rollout-20260302-120106120000-thread_123.jsonl"
    old_path.write_text("", encoding="utf-8")
    new_path.write_text("", encoding="utf-8")

    latest = resolve_latest_rollout("thread:123", root=tmp_path)

    assert latest == new_path


def test_sanitize_thread_id_uses_safe_filename_chars() -> None:
    assert sanitize_thread_id(" thread id / foo ") == "thread_id_foo"
    assert sanitize_thread_id("%%%") == "thread"


@pytest.mark.asyncio
async def test_rollout_recorder_record_and_flush_writes_jsonl_in_order(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "rollout-20260302-120105120000-thread_123.jsonl"
    recorder = RolloutRecorder(path=path)

    await recorder.record(
        [
            SessionMeta(
                schema_version=SCHEMA_VERSION,
                thread_id="thread_123",
                profile="codex",
                model="gpt-4.1-mini",
                cwd="/tmp/project",
                opened_at="2026-03-02T12:01:05Z",
                import_source=None,
            )
        ]
    )
    await recorder.record(
        [
            HistoryItem(
                schema_version=SCHEMA_VERSION,
                thread_id="thread_123",
                item={"role": "user", "content": "hello"},
            )
        ]
    )
    await recorder.flush()
    await recorder.shutdown()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert '"type":"session.meta"' in lines[0]
    assert '"type":"history.item"' in lines[1]


@pytest.mark.asyncio
async def test_rollout_recorder_shutdown_flushes_pending_writes(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "rollout-20260302-120105120000-thread_123.jsonl"
    recorder = RolloutRecorder(path=path)
    await recorder.record(
        [
            HistoryItem(
                schema_version=SCHEMA_VERSION,
                thread_id="thread_123",
                item={"role": "assistant", "content": "done"},
            )
        ]
    )

    await recorder.shutdown()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert '"type":"history.item"' in lines[0]


@pytest.mark.asyncio
async def test_rollout_recorder_shutdown_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "rollout-20260302-120105120000-thread_123.jsonl"
    recorder = RolloutRecorder(path=path)
    await recorder.shutdown()
    await recorder.shutdown()
