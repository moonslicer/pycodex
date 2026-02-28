from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pycodex.__main__ as main_module
import pytest
from pycodex.core.agent import ToolCallDispatched, ToolResultReceived, TurnCompleted, TurnStarted
from pycodex.core.config import Config
from pycodex.core.session import Session

pytestmark = pytest.mark.integration


class _FakeModelClient:
    def __init__(self, config: Config) -> None:
        self.config = config


def test_main_help_exits_with_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["--help"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert "--approval" in captured.out
    assert "prompt" in captured.out


def test_main_missing_prompt_exits_with_parser_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_module.main([])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_main_runs_turn_and_prints_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
    )

    async def fake_run_turn(
        *,
        session: Session,
        model_client: _FakeModelClient,
        tool_router: Any,
        cwd: Path,
        user_input: str,
    ) -> str:
        assert isinstance(session, Session)
        assert session.config == config
        assert isinstance(model_client, _FakeModelClient)
        assert cwd == tmp_path
        assert user_input == "hello from cli"

        tool_names = {
            spec["function"]["name"]
            for spec in tool_router.tool_specs()
            if spec.get("type") == "function" and isinstance(spec.get("function"), dict)
        }
        assert tool_names == main_module.EXPECTED_TOOL_NAMES

        return "final-answer"

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "ModelClient", _FakeModelClient)
    monkeypatch.setattr(main_module, "run_turn", fake_run_turn)

    exit_code = main_module.main(["hello from cli"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "final-answer"


def test_main_returns_error_code_and_stderr_on_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
    )

    async def failing_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
    ) -> str:
        _ = session, model_client, tool_router, cwd, user_input
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "run_turn", failing_run_turn)

    exit_code = main_module.main(["hello from cli"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[ERROR] boom"


def test_main_passes_approval_policy_to_run_prompt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    async def fake_run_prompt(prompt: str, *, approval_policy: main_module.ApprovalPolicy) -> str:
        seen["prompt"] = prompt
        seen["approval_policy"] = approval_policy
        return "final-answer"

    monkeypatch.setattr(main_module, "_run_prompt", fake_run_prompt)

    exit_code = main_module.main(["--approval", "on-request", "hello from cli"])

    assert exit_code == 0
    assert seen == {
        "prompt": "hello from cli",
        "approval_policy": main_module.ApprovalPolicy.ON_REQUEST,
    }
    captured = capsys.readouterr()
    assert captured.out.strip() == "final-answer"


def test_json_flag_emits_valid_jsonl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
    )

    async def fake_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
        on_event: Any = None,
    ) -> str:
        _ = session, model_client, tool_router, cwd
        assert user_input == "hello from cli"
        assert on_event is not None
        on_event(TurnStarted(user_input=user_input))
        on_event(TurnCompleted(final_text="done"))
        return "final-answer"

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "ModelClient", _FakeModelClient)
    monkeypatch.setattr(main_module, "run_turn", fake_run_turn)

    exit_code = main_module.main(["--json", "hello from cli"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.splitlines()
    assert lines
    parsed = [json.loads(line) for line in lines]
    assert all("type" in line for line in parsed)


def test_json_flag_event_ordering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
    )

    async def fake_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
        on_event: Any = None,
    ) -> str:
        _ = session, model_client, tool_router, cwd, user_input
        assert on_event is not None
        on_event(TurnStarted(user_input="hello from cli"))
        on_event(ToolCallDispatched(call_id="call_1", name="shell", arguments='{"command":"pwd"}'))
        on_event(ToolResultReceived(call_id="call_1", name="shell", result="/tmp"))
        on_event(TurnCompleted(final_text="done"))
        return "final-answer"

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "ModelClient", _FakeModelClient)
    monkeypatch.setattr(main_module, "run_turn", fake_run_turn)

    exit_code = main_module.main(["--json", "hello from cli"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    types = [json.loads(line)["type"] for line in captured.out.splitlines()]
    assert types == [
        "thread.started",
        "turn.started",
        "item.started",
        "item.completed",
        "turn.completed",
    ]


def test_json_flag_turn_failed_on_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
    )

    async def failing_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
        on_event: Any = None,
    ) -> str:
        _ = session, model_client, tool_router, cwd, user_input, on_event
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "run_turn", failing_run_turn)

    exit_code = main_module.main(["--json", "hello from cli"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = [json.loads(line) for line in captured.out.splitlines()]
    assert lines[0]["type"] == "thread.started"
    assert lines[-1]["type"] == "turn.failed"
    assert lines[-1]["thread_id"] == lines[0]["thread_id"]
    assert lines[-1]["turn_id"] == "turn_1"
    assert "boom" in lines[-1]["error"]


def test_json_flag_turn_failed_before_turn_started_uses_fallback_turn_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
    )

    async def failing_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
        on_event: Any = None,
    ) -> str:
        _ = session, model_client, tool_router, cwd, user_input, on_event
        raise RuntimeError("early boom")

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "run_turn", failing_run_turn)

    exit_code = main_module.main(["--json", "hello from cli"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = [json.loads(line) for line in captured.out.splitlines()]
    assert [line["type"] for line in lines] == ["thread.started", "turn.failed"]
    assert lines[-1]["turn_id"] == "turn_1"
    assert lines[-1]["thread_id"] == lines[0]["thread_id"]


def test_json_flag_turn_failed_after_turn_started_uses_active_turn_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
    )

    async def failing_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
        on_event: Any = None,
    ) -> str:
        _ = session, model_client, tool_router, cwd, user_input
        assert on_event is not None
        on_event(TurnStarted(user_input="hello from cli"))
        raise RuntimeError("late boom")

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "run_turn", failing_run_turn)

    exit_code = main_module.main(["--json", "hello from cli"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = [json.loads(line) for line in captured.out.splitlines()]
    assert [line["type"] for line in lines] == [
        "thread.started",
        "turn.started",
        "turn.failed",
    ]
    assert lines[-1]["turn_id"] == "turn_1"
    assert "late boom" in lines[-1]["error"]


def test_main_json_mode_top_level_exception_reports_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def failing_run_prompt_json(
        prompt: str,
        *,
        approval_policy: main_module.ApprovalPolicy,
    ) -> int:
        _ = prompt, approval_policy
        raise RuntimeError()

    monkeypatch.setattr(main_module, "_run_prompt_json", failing_run_prompt_json)

    exit_code = main_module.main(["--json", "hello from cli"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[ERROR] RuntimeError"


def test_text_mode_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
    )

    async def fake_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
    ) -> str:
        _ = session, model_client, tool_router, cwd, user_input
        return "final-answer"

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "run_turn", fake_run_turn)

    exit_code = main_module.main(["hello from cli"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.strip() == "final-answer"
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured.out)
