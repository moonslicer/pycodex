from __future__ import annotations

import json
from pathlib import Path

import pytest
from pycodex.core.rollout_replay import import_legacy_session_json, replay_rollout


@pytest.mark.asyncio
async def test_import_legacy_session_json_creates_rollout_with_source_marker(
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "legacy-thread.json"
    legacy_payload = {
        "cwd": "/tmp/project",
        "history": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    }
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    rollout_path = await import_legacy_session_json(
        legacy_path,
        sessions_root=tmp_path / "sessions",
    )
    state = replay_rollout(rollout_path)

    assert state.thread_id == "legacy-thread"
    assert state.session_meta is not None
    assert state.session_meta.import_source == "legacy_json"
    assert state.history == legacy_payload["history"]


@pytest.mark.asyncio
async def test_import_legacy_session_json_is_idempotent(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy-thread.json"
    legacy_payload = {
        "cwd": "/tmp/project",
        "history": [{"role": "user", "content": "hello"}],
    }
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    sessions_root = tmp_path / "sessions"

    first = await import_legacy_session_json(legacy_path, sessions_root=sessions_root)
    second = await import_legacy_session_json(legacy_path, sessions_root=sessions_root)

    assert first == second
    rollout_files = sorted(sessions_root.glob("rollout-*.jsonl"))
    assert rollout_files == [first]
