from __future__ import annotations

from pathlib import Path
from typing import Any

import pycodex.__main__ as main_module
import pytest
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
