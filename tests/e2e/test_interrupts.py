from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pycodex.__main__ as main_module
import pytest
from pycodex.core.agent import TurnStarted
from pycodex.core.config import Config
from pycodex.core.session import Session

pytestmark = pytest.mark.e2e


def test_cli_text_mode_ctrl_c_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)

    async def interrupted_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
    ) -> str:
        _ = session, model_client, tool_router, cwd, user_input
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "run_turn", interrupted_run_turn)

    exit_code = main_module.main(["long running prompt"])

    assert exit_code == main_module.INTERRUPTED_EXIT_CODE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[ERROR] interrupted"


def test_cli_json_mode_ctrl_c_emits_turn_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)

    async def interrupted_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
        on_event: Any = None,
    ) -> str:
        _ = session, model_client, tool_router, cwd
        assert on_event is not None
        on_event(TurnStarted(user_input=user_input))
        raise asyncio.CancelledError

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "run_turn", interrupted_run_turn)

    exit_code = main_module.main(["--json", "long running prompt"])

    assert exit_code == main_module.INTERRUPTED_EXIT_CODE
    captured = capsys.readouterr()
    assert captured.err == ""
    events = [json.loads(line) for line in captured.out.splitlines() if line.strip()]
    assert [event["type"] for event in events] == [
        "thread.started",
        "turn.started",
        "turn.failed",
    ]
    assert events[-1]["error"] == "interrupted"
