from __future__ import annotations

import json
from pathlib import Path

import pycodex.__main__ as main_module
import pytest
from pycodex.core.config import Config

pytestmark = pytest.mark.e2e


def _read_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def test_session_resume_appends_to_existing_rollout(
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

    rollout_files = sorted((tmp_path / "sessions").glob("rollout-*.jsonl"))
    assert len(rollout_files) == 1
    rollout_path = rollout_files[0]
    first_records = _read_records(rollout_path)
    thread_id = str(first_records[0]["thread_id"])

    second_exit = main_module.main(["--resume", thread_id, "second prompt"])
    assert second_exit == 0
    capsys.readouterr()

    second_records = _read_records(rollout_path)
    assert len(second_records) > len(first_records)
    assert sum(1 for record in second_records if record["type"] == "session.meta") == 1
    assert sum(1 for record in second_records if record["type"] == "session.closed") == 2


def test_session_resume_recovers_from_truncated_last_line(
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

    rollout_path = sorted((tmp_path / "sessions").glob("rollout-*.jsonl"))[0]
    records = _read_records(rollout_path)
    thread_id = str(records[0]["thread_id"])

    with rollout_path.open("a", encoding="utf-8") as handle:
        handle.write('{"schema_version":"1.0"')

    resumed_exit = main_module.main(["--resume", thread_id, "next prompt"])
    assert resumed_exit == 0
    captured = capsys.readouterr()
    assert "[ERROR]" not in captured.err
