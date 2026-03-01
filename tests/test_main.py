from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pycodex.__main__ as main_module
import pytest
from pycodex.core.agent import ToolCallDispatched, ToolResultReceived, TurnCompleted, TurnStarted
from pycodex.core.agent_profile import CODEX_PROFILE, AgentProfile
from pycodex.core.config import Config
from pycodex.core.fake_model_client import FakeModelClient
from pycodex.core.session import Session

pytestmark = pytest.mark.integration

ABORT_TEXT = "Aborted by user."


class _FakeModelClient:
    def __init__(self, config: Config) -> None:
        self.config = config


def test_main_help_exits_with_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["--help"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    normalized_help = " ".join(captured.out.split())
    assert "usage:" in captured.out
    assert "--approval" in captured.out
    assert "prompt" in captured.out
    assert re.search(r"required unless --tui-\s*mode", captured.out) is not None
    assert "requires prompt" in normalized_help


def test_main_missing_prompt_exits_with_parser_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_module.main([])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_sandbox_flag_default_is_danger_full_access() -> None:
    args = main_module._build_parser().parse_args([])
    assert args.sandbox == "danger-full-access"


def test_sandbox_flag_accepted_values() -> None:
    args = main_module._build_parser().parse_args(["--sandbox", "read-only", "x"])
    assert args.sandbox == "read-only"


def test_profile_flag_is_parsed() -> None:
    args = main_module._build_parser().parse_args(["--profile", "codex", "x"])
    assert args.profile == "codex"


def test_instructions_file_flag_is_parsed() -> None:
    args = main_module._build_parser().parse_args(["--instructions-file", "/tmp/i.txt", "x"])
    assert args.instructions_file == "/tmp/i.txt"


def test_resolve_profile_override_uses_builtin_profile() -> None:
    resolved = main_module._resolve_profile_override(
        default_profile=CODEX_PROFILE,
        profile="codex",
        profile_file=None,
        instructions=None,
        instructions_file=None,
    )

    assert resolved == CODEX_PROFILE


def test_resolve_profile_override_supports_profile_file_and_instruction_override(
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "profile.toml"
    profile_path.write_text(
        "\n".join(
            [
                'name = "support"',
                'instructions = "Support instructions."',
                'instruction_filenames = ["SUPPORT.md"]',
            ]
        ),
        encoding="utf-8",
    )

    resolved = main_module._resolve_profile_override(
        default_profile=CODEX_PROFILE,
        profile=None,
        profile_file=str(profile_path),
        instructions="Override instructions.",
        instructions_file=None,
    )

    assert resolved == AgentProfile(
        name="support",
        instructions="Override instructions.",
        instruction_filenames=("SUPPORT.md",),
        enabled_tools=None,
    )


def test_resolve_profile_override_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="Unknown profile"):
        main_module._resolve_profile_override(
            default_profile=CODEX_PROFILE,
            profile="nope",
            profile_file=None,
            instructions=None,
            instructions_file=None,
        )


def test_resolve_profile_override_rejects_empty_instructions_override() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        main_module._resolve_profile_override(
            default_profile=CODEX_PROFILE,
            profile=None,
            profile_file=None,
            instructions="   ",
            instructions_file=None,
        )


def test_main_json_missing_prompt_exits_with_parser_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["--json"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_tui_mode_runs_tui_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    async def fake_run_tui_mode(
        *,
        approval_policy: main_module.ApprovalPolicy,
        sandbox_policy: main_module.SandboxPolicy,
    ) -> int:
        seen["approval_policy"] = approval_policy
        seen["sandbox_policy"] = sandbox_policy
        return 0

    monkeypatch.setattr(main_module, "_run_tui_mode", fake_run_tui_mode)

    exit_code = main_module.main(["--tui-mode", "--approval", "on-request"])

    assert exit_code == 0
    assert seen == {
        "approval_policy": main_module.ApprovalPolicy.ON_REQUEST,
        "sandbox_policy": main_module.SandboxPolicy.DANGER_FULL_ACCESS,
    }
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_tui_mode_with_prompt_exits_with_parser_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["--tui-mode", "hello from cli"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_tui_mode_with_json_exits_with_parser_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["--tui-mode", "--json"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_tui_mode_top_level_exception_reports_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def failing_run_tui_mode(
        *,
        approval_policy: main_module.ApprovalPolicy,
        sandbox_policy: main_module.SandboxPolicy,
    ) -> int:
        _ = approval_policy, sandbox_policy
        raise RuntimeError()

    monkeypatch.setattr(main_module, "_run_tui_mode", failing_run_tui_mode)

    exit_code = main_module.main(["--tui-mode"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[ERROR] RuntimeError"


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

    async def fake_run_prompt(
        prompt: str,
        *,
        approval_policy: main_module.ApprovalPolicy,
        sandbox_policy: main_module.SandboxPolicy,
    ) -> str:
        seen["prompt"] = prompt
        seen["approval_policy"] = approval_policy
        seen["sandbox_policy"] = sandbox_policy
        return "final-answer"

    monkeypatch.setattr(main_module, "_run_prompt", fake_run_prompt)

    exit_code = main_module.main(["--approval", "on-request", "hello from cli"])

    assert exit_code == 0
    assert seen == {
        "prompt": "hello from cli",
        "approval_policy": main_module.ApprovalPolicy.ON_REQUEST,
        "sandbox_policy": main_module.SandboxPolicy.DANGER_FULL_ACCESS,
    }
    captured = capsys.readouterr()
    assert captured.out.strip() == "final-answer"


def test_main_passes_profile_overrides_to_run_prompt_when_provided(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    async def fake_run_prompt(
        prompt: str,
        *,
        approval_policy: main_module.ApprovalPolicy,
        sandbox_policy: main_module.SandboxPolicy,
        profile: str | None = None,
        profile_file: str | None = None,
        instructions: str | None = None,
        instructions_file: str | None = None,
    ) -> str:
        seen["prompt"] = prompt
        seen["approval_policy"] = approval_policy
        seen["sandbox_policy"] = sandbox_policy
        seen["profile"] = profile
        seen["profile_file"] = profile_file
        seen["instructions"] = instructions
        seen["instructions_file"] = instructions_file
        return "final-answer"

    monkeypatch.setattr(main_module, "_run_prompt", fake_run_prompt)

    exit_code = main_module.main(
        [
            "--profile",
            "codex",
            "--instructions",
            "You are a test assistant.",
            "hello from cli",
        ]
    )

    assert exit_code == 0
    assert seen == {
        "prompt": "hello from cli",
        "approval_policy": main_module.ApprovalPolicy.NEVER,
        "sandbox_policy": main_module.SandboxPolicy.DANGER_FULL_ACCESS,
        "profile": "codex",
        "profile_file": None,
        "instructions": "You are a test assistant.",
        "instructions_file": None,
    }
    captured = capsys.readouterr()
    assert captured.out.strip() == "final-answer"


def test_main_unknown_profile_returns_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main_module.main(["--profile", "unknown", "hello from cli"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Unknown profile" in captured.err


def test_main_empty_instructions_returns_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main_module.main(["--instructions", " ", "hello from cli"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "non-empty" in captured.err


def test_main_passes_explicit_sandbox_policy_to_run_prompt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    async def fake_run_prompt(
        prompt: str,
        *,
        approval_policy: main_module.ApprovalPolicy,
        sandbox_policy: main_module.SandboxPolicy,
    ) -> str:
        seen["prompt"] = prompt
        seen["approval_policy"] = approval_policy
        seen["sandbox_policy"] = sandbox_policy
        return "final-answer"

    monkeypatch.setattr(main_module, "_run_prompt", fake_run_prompt)

    exit_code = main_module.main(["--sandbox", "workspace-write", "hello from cli"])

    assert exit_code == 0
    assert seen == {
        "prompt": "hello from cli",
        "approval_policy": main_module.ApprovalPolicy.NEVER,
        "sandbox_policy": main_module.SandboxPolicy.WORKSPACE_WRITE,
    }
    captured = capsys.readouterr()
    assert captured.out.strip() == "final-answer"


def test_main_passes_explicit_sandbox_policy_to_run_prompt_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    async def fake_run_prompt_json(
        prompt: str,
        *,
        approval_policy: main_module.ApprovalPolicy,
        sandbox_policy: main_module.SandboxPolicy,
    ) -> int:
        seen["prompt"] = prompt
        seen["approval_policy"] = approval_policy
        seen["sandbox_policy"] = sandbox_policy
        return 0

    monkeypatch.setattr(main_module, "_run_prompt_json", fake_run_prompt_json)

    exit_code = main_module.main(["--json", "--sandbox", "read-only", "hello from cli"])

    assert exit_code == 0
    assert seen == {
        "prompt": "hello from cli",
        "approval_policy": main_module.ApprovalPolicy.NEVER,
        "sandbox_policy": main_module.SandboxPolicy.READ_ONLY,
    }
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_sandbox_flag_wires_to_orchestrator_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
    )
    seen: dict[str, object] = {}

    def fake_build_tool_router(
        *,
        approval_policy: main_module.ApprovalPolicy,
        sandbox_policy: main_module.SandboxPolicy,
        ask_user_fn: main_module.AskUserFn | None = None,
    ) -> Any:
        seen["approval_policy"] = approval_policy
        seen["sandbox_policy"] = sandbox_policy
        seen["ask_user_fn"] = ask_user_fn
        return main_module.ToolRouter(main_module.ToolRegistry())

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
    monkeypatch.setattr(main_module, "ModelClient", _FakeModelClient)
    monkeypatch.setattr(main_module, "_build_tool_router", fake_build_tool_router)
    monkeypatch.setattr(main_module, "run_turn", fake_run_turn)

    exit_code = main_module.main(["--sandbox", "read-only", "hello from cli"])

    assert exit_code == 0
    assert seen["approval_policy"] == main_module.ApprovalPolicy.NEVER
    assert seen["sandbox_policy"] == main_module.SandboxPolicy.READ_ONLY
    assert seen["ask_user_fn"] is None
    captured = capsys.readouterr()
    assert captured.out.strip() == "final-answer"


def test_tui_mode_passes_explicit_sandbox_policy(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    async def fake_run_tui_mode(
        *,
        approval_policy: main_module.ApprovalPolicy,
        sandbox_policy: main_module.SandboxPolicy,
    ) -> int:
        seen["approval_policy"] = approval_policy
        seen["sandbox_policy"] = sandbox_policy
        return 0

    monkeypatch.setattr(main_module, "_run_tui_mode", fake_run_tui_mode)

    exit_code = main_module.main(["--tui-mode", "--sandbox", "workspace-write"])

    assert exit_code == 0
    assert seen == {
        "approval_policy": main_module.ApprovalPolicy.NEVER,
        "sandbox_policy": main_module.SandboxPolicy.WORKSPACE_WRITE,
    }
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_build_tool_router_wires_exec_policy_fn() -> None:
    router = main_module._build_tool_router(
        approval_policy=main_module.ApprovalPolicy.NEVER,
        sandbox_policy=main_module.SandboxPolicy.DANGER_FULL_ACCESS,
    )
    orchestrator = router._registry._orchestrator
    assert orchestrator is not None
    assert callable(orchestrator.exec_policy_fn)


def test_build_tool_router_forbidden_command_blocks_before_prompt(tmp_path: Path) -> None:
    ask_user_calls = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> main_module.ReviewDecision:
        nonlocal ask_user_calls
        ask_user_calls += 1
        return main_module.ReviewDecision.APPROVED

    router = main_module._build_tool_router(
        approval_policy=main_module.ApprovalPolicy.ON_REQUEST,
        sandbox_policy=main_module.SandboxPolicy.DANGER_FULL_ACCESS,
        ask_user_fn=ask_user_fn,
    )

    raw_result = asyncio.run(
        router.dispatch(
            name="shell",
            arguments={"command": "rm -rf /"},
            cwd=tmp_path,
        )
    )
    outcome = json.loads(raw_result)

    assert outcome["success"] is False
    assert outcome["error"]["code"] == "forbidden"
    assert ask_user_calls == 0


def test_build_model_client_uses_real_model_client_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("PYCODEX_FAKE_MODEL", raising=False)
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)

    model_client = main_module._build_model_client(config)

    assert isinstance(model_client, main_module.ModelClient)


def test_build_model_client_uses_fake_model_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PYCODEX_FAKE_MODEL", "1")
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)

    model_client = main_module._build_model_client(config)

    assert isinstance(model_client, FakeModelClient)


def test_json_mode_fake_model_produces_completed_event_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PYCODEX_FAKE_MODEL", "1")
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)
    monkeypatch.setattr(main_module, "load_config", lambda: config)

    exit_code = main_module.main(["--json", "what is 2+2"])

    assert exit_code == 0
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.strip()]
    assert [event["type"] for event in events] == [
        "thread.started",
        "turn.started",
        "item.updated",
        "turn.completed",
    ]
    assert events[-1]["final_text"] == "4"


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


@pytest.mark.parametrize(
    "inject_unknown_event",
    [False, True],
    ids=["abort-only", "abort-with-unknown-event"],
)
def test_json_flag_abort_mapping_ignores_unknown_agent_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    inject_unknown_event: bool,
) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
    )

    class _UnknownAgentEvent:
        pass

    async def aborting_run_turn(
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
        if inject_unknown_event:
            on_event(_UnknownAgentEvent())
        on_event(TurnCompleted(final_text=ABORT_TEXT))
        return ABORT_TEXT

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "run_turn", aborting_run_turn)

    exit_code = main_module.main(["--json", "hello from cli"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = [json.loads(line) for line in captured.out.splitlines()]
    assert [line["type"] for line in lines] == [
        "thread.started",
        "turn.started",
        "turn.completed",
    ]
    assert lines[-1]["final_text"] == ABORT_TEXT


def test_main_json_mode_top_level_exception_reports_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def failing_run_prompt_json(
        prompt: str,
        *,
        approval_policy: main_module.ApprovalPolicy,
        sandbox_policy: main_module.SandboxPolicy,
    ) -> int:
        _ = prompt, approval_policy, sandbox_policy
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
