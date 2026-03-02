from __future__ import annotations

import json
from pathlib import Path

import pycodex.__main__ as main_module
import pytest
from pycodex.core.config import Config

pytestmark = pytest.mark.e2e


def _session_thread_id(path: Path) -> str:
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    payload = json.loads(first_line)
    return str(payload["thread_id"])


def test_session_archive_and_unarchive_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PYCODEX_FAKE_MODEL", "1")
    monkeypatch.setattr(main_module, "default_sessions_root", lambda: tmp_path / "sessions")
    monkeypatch.setattr(
        main_module, "default_archived_sessions_root", lambda: tmp_path / "archived"
    )
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)
    monkeypatch.setattr(main_module, "load_config", lambda: config)

    first_exit = main_module.main(["first prompt"])
    assert first_exit == 0
    capsys.readouterr()

    session_path = sorted((tmp_path / "sessions").glob("rollout-*.jsonl"))[0]
    thread_id = _session_thread_id(session_path)

    archive_exit = main_module.main(["session", "archive", thread_id])
    assert archive_exit == 0
    capsys.readouterr()
    assert not session_path.exists()

    archived_paths = sorted((tmp_path / "archived").glob("rollout-*.jsonl"))
    assert len(archived_paths) == 1

    unarchive_exit = main_module.main(["session", "unarchive", thread_id])
    assert unarchive_exit == 0
    capsys.readouterr()
    assert archived_paths[0].exists() is False
    restored_paths = sorted((tmp_path / "sessions").glob("rollout-*.jsonl"))
    assert len(restored_paths) == 1

    list_exit = main_module.main(["session", "list"])
    assert list_exit == 0
    list_output = capsys.readouterr().out
    assert thread_id in list_output

    read_exit = main_module.main(["session", "read", thread_id])
    assert read_exit == 0
    read_output = capsys.readouterr().out.strip()
    summary = json.loads(read_output)
    assert summary["thread_id"] == thread_id
