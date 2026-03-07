from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pycodex.core.agent import Agent
from pycodex.core.compaction import CompactionApplied
from pycodex.core.config import Config
from pycodex.core.model_client import Completed, OutputItemDone, OutputTextDelta
from pycodex.core.rollout_recorder import (
    RolloutRecorder,
    build_rollout_path,
    resolve_latest_rollout,
    sanitize_thread_id,
)
from pycodex.core.rollout_schema import SCHEMA_VERSION, HistoryItem, SessionMeta
from pycodex.core.session import Session


class _FakeModelClient:
    def __init__(self, turns: list[list[Any]]) -> None:
        self._turns = turns

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        instructions: str = "",
    ):
        _ = messages, tools, instructions
        if not self._turns:
            raise AssertionError("No configured turns left.")
        for event in self._turns.pop(0):
            yield event


class _FakeToolRouter:
    def tool_specs(self) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": "read_file"}}]

    async def dispatch(self, *, name: str, arguments: str | dict[str, Any], cwd: Path) -> str:
        _ = name, arguments, cwd
        return "tool ok"


class _SingleCompaction:
    def __init__(self) -> None:
        self._used = False

    async def compact(self, session: Session) -> CompactionApplied | None:
        if self._used:
            return None
        self._used = True
        session.replace_prefix_with_system_summary(
            replace_count=1,
            summary_text="[compaction.summary.v1]\nConversation summary:\n- user: hello",
        )
        return CompactionApplied(
            strategy="threshold_v1",
            implementation="local_summary_v1",
            replace_start=0,
            replace_end=1,
            replaced_items=1,
            estimated_prompt_tokens=400,
            context_window_tokens=1000,
            remaining_ratio=0.1,
            threshold_ratio=0.2,
            summary_text="[compaction.summary.v1]\nConversation summary:\n- user: hello",
        )


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


@pytest.mark.asyncio
async def test_rollout_recorder_shutdown_is_idempotent_after_writes(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "rollout-20260302-120105120000-thread_123.jsonl"
    recorder = RolloutRecorder(path=path)
    await recorder.record(
        [
            HistoryItem(
                schema_version=SCHEMA_VERSION,
                thread_id="thread_123",
                item={"role": "user", "content": "hello"},
            )
        ]
    )
    await recorder.shutdown()
    content_after_first = path.read_text(encoding="utf-8")

    await recorder.shutdown()

    assert path.read_text(encoding="utf-8") == content_after_first


@pytest.mark.asyncio
async def test_rollout_recorder_record_raises_after_shutdown(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "rollout-20260302-120105120000-thread_123.jsonl"
    recorder = RolloutRecorder(path=path)
    await recorder.shutdown()

    with pytest.raises(RuntimeError, match="already closed"):
        await recorder.record(
            [
                HistoryItem(
                    schema_version=SCHEMA_VERSION,
                    thread_id="thread_123",
                    item={"role": "user", "content": "late"},
                )
            ]
        )


@pytest.mark.asyncio
async def test_rollout_recorder_flush_is_noop_after_shutdown(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "rollout-20260302-120105120000-thread_123.jsonl"
    recorder = RolloutRecorder(path=path)
    await recorder.shutdown()
    # flush() after shutdown is a no-op — should not raise
    await recorder.flush()


@pytest.mark.asyncio
async def test_rollout_recorder_preserves_valid_unterminated_last_line(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "rollout-20260302-120105120000-thread_123.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    first = {
        "schema_version": SCHEMA_VERSION,
        "type": "history.item",
        "thread_id": "thread_123",
        "item": {"role": "user", "content": "first"},
    }
    # Simulate a crash after writing valid JSON but before writing trailing newline.
    path.write_text(json.dumps(first, ensure_ascii=True), encoding="utf-8")

    recorder = RolloutRecorder(path=path)
    await recorder.record(
        [
            HistoryItem(
                schema_version=SCHEMA_VERSION,
                thread_id="thread_123",
                item={"role": "user", "content": "second"},
            )
        ]
    )
    await recorder.shutdown()

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0] == first
    assert parsed[1]["item"]["content"] == "second"


def test_rollout_recorder_flush_timeout_field_has_default() -> None:
    recorder = RolloutRecorder(path=Path(os.devnull))
    assert recorder.flush_timeout == 30.0


def test_rollout_recorder_flush_timeout_field_is_configurable() -> None:
    recorder = RolloutRecorder(path=Path(os.devnull), flush_timeout=5.0)
    assert recorder.flush_timeout == 5.0


@pytest.mark.asyncio
async def test_rollout_write_points_persist_meta_history_turn_and_close(tmp_path: Path) -> None:
    config = Config(model="gpt-4.1-mini", api_key="test", cwd=tmp_path)
    session = Session(config=config, thread_id="thread_123")
    path = build_rollout_path(
        session.thread_id,
        now=datetime(2026, 3, 2, 12, 1, 5, 120000, tzinfo=UTC),
        root=tmp_path / "sessions",
    )
    session.configure_rollout_recorder(recorder=RolloutRecorder(path=path), path=path)
    agent = Agent(
        session=session,
        model_client=_FakeModelClient(
            turns=[
                [
                    OutputTextDelta(delta="hello"),
                    Completed(
                        response_id="resp_1",
                        usage={"input_tokens": 10, "output_tokens": 4},
                    ),
                ]
            ]
        ),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
    )

    result = await agent.run_turn("hi")
    await session.close_rollout()

    assert result == "hello"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    types = [record["type"] for record in records]
    assert types == [
        "session.meta",
        "history.item",
        "history.item",
        "turn.completed",
        "session.closed",
    ]
    assert records[3]["usage"]["cumulative"] == {"input_tokens": 10, "output_tokens": 4}
    assert records[4]["turn_count"] == 1


@pytest.mark.asyncio
async def test_rollout_write_points_include_compaction_applied_record(tmp_path: Path) -> None:
    config = Config(
        model="gpt-4.1-mini",
        api_key="test",
        cwd=tmp_path,
        compaction_threshold_ratio=0.2,
        compaction_options={"strategy": {"threshold_ratio": 0.2}},
    )
    session = Session(config=config, thread_id="thread_123")
    path = build_rollout_path(
        session.thread_id,
        now=datetime(2026, 3, 2, 12, 1, 5, 120000, tzinfo=UTC),
        root=tmp_path / "sessions",
    )
    session.configure_rollout_recorder(recorder=RolloutRecorder(path=path), path=path)
    session.append_user_message("seed")
    agent = Agent(
        session=session,
        model_client=_FakeModelClient(
            turns=[
                [
                    OutputItemDone(
                        item={
                            "type": "function_call",
                            "call_id": "call_1",
                            "name": "read_file",
                            "arguments": "{}",
                        }
                    ),
                    Completed(
                        response_id="resp_1",
                        usage={"input_tokens": 4, "output_tokens": 2},
                    ),
                ],
                [
                    OutputTextDelta(delta="done"),
                    Completed(
                        response_id="resp_2",
                        usage={"input_tokens": 6, "output_tokens": 3},
                    ),
                ],
            ]
        ),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
        compaction_orchestrator=_SingleCompaction(),
    )

    await agent.run_turn("hi")
    await session.close_rollout()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    compaction_records = [record for record in records if record["type"] == "compaction.applied"]

    assert len(compaction_records) == 1
    assert compaction_records[0]["strategy"] == "threshold_v1"
    assert compaction_records[0]["implementation"] == "local_summary_v1"
    assert compaction_records[0]["replace_start"] == 0


@pytest.mark.asyncio
async def test_rollout_recorder_concurrent_records_do_not_interleave(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "rollout.jsonl"
    recorder = RolloutRecorder(path=path)

    # Fire 50 concurrent record() calls — each with one item
    items = [
        HistoryItem(
            schema_version=SCHEMA_VERSION,
            thread_id="thread_123",
            item={"role": "user", "content": f"msg-{i}"},
        )
        for i in range(50)
    ]
    await asyncio.gather(*[recorder.record([item]) for item in items])
    await recorder.shutdown()

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 50
    # Every line must be valid JSON — no interleaving would corrupt JSON
    parsed = [json.loads(line) for line in lines]
    assert all(p["type"] == "history.item" for p in parsed)
    contents = {json.loads(line)["item"]["content"] for line in lines}
    assert contents == {f"msg-{i}" for i in range(50)}
