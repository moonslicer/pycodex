from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pycodex.__main__ as main_module
import pytest
from pycodex.core.config import Config
from pycodex.core.model_client import Completed, OutputItemDone, OutputTextDelta

pytestmark = pytest.mark.e2e


def _tool_payload(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for item in messages:
        if item.get("role") != "tool":
            continue
        content = item.get("content")
        assert isinstance(content, str)
        payload = json.loads(content)
        assert isinstance(payload, dict)
        return payload
    raise AssertionError("expected at least one tool message")


def test_cli_e2e_shell_timeout_surfaces_structured_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)
    holder: dict[str, Any] = {}

    class _FakeModelClient:
        def __init__(self, _config: Config, request_observer: Any | None = None) -> None:
            _ = request_observer
            self.calls: list[list[dict[str, Any]]] = []
            holder["client"] = self

        async def stream(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            instructions: str = "",
        ):
            _ = tools, instructions
            self.calls.append([dict(message) for message in messages])

            if len(self.calls) == 1:
                yield OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "shell",
                        "arguments": '{"command":"sleep 0.2","timeout_ms":20}',
                        "call_id": "call_timeout",
                    }
                )
                yield Completed(response_id="resp_tool")
                return

            assert len(self.calls) == 2
            payload = _tool_payload(self.calls[1])
            assert payload["success"] is False
            assert payload["error"]["code"] == "timeout"
            assert "timed out" in payload["body"]
            yield OutputTextDelta(delta="timeout handled")
            yield Completed(response_id="resp_done")

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "ModelClient", _FakeModelClient)

    exit_code = main_module.main(["--approval", "never", "run a command that times out"])

    assert exit_code == 0
    assert len(holder["client"].calls) == 2
    captured = capsys.readouterr()
    assert captured.out.strip() == "timeout handled"
    assert captured.err == ""


def test_cli_e2e_shell_timeout_reports_unclean_termination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)
    holder: dict[str, Any] = {}

    class _HangingProcess:
        returncode = None

        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(30)
            return (b"", b"")

        def kill(self) -> None:
            return None

    async def fake_create_subprocess_exec(
        *argv: str,
        cwd: Path,
        stdout: int,
        stderr: int,
    ) -> _HangingProcess:
        _ = argv, cwd, stdout, stderr
        return _HangingProcess()

    class _FakeModelClient:
        def __init__(self, _config: Config, request_observer: Any | None = None) -> None:
            _ = request_observer
            self.calls: list[list[dict[str, Any]]] = []
            holder["client"] = self

        async def stream(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            instructions: str = "",
        ):
            _ = tools, instructions
            self.calls.append([dict(message) for message in messages])

            if len(self.calls) == 1:
                yield OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "shell",
                        "arguments": '{"command":"sleep 0.2","timeout_ms":1}',
                        "call_id": "call_timeout_unclean",
                    }
                )
                yield Completed(response_id="resp_tool")
                return

            assert len(self.calls) == 2
            payload = _tool_payload(self.calls[1])
            assert payload["success"] is False
            assert payload["error"]["code"] == "timeout"
            assert "could not be terminated cleanly" in payload["body"]
            yield OutputTextDelta(delta="unclean timeout handled")
            yield Completed(response_id="resp_done")

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "ModelClient", _FakeModelClient)
    monkeypatch.setattr(
        "pycodex.tools.shell.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr("pycodex.tools.shell._POST_KILL_WAIT_SECONDS", 0.001)

    exit_code = main_module.main(["--approval", "never", "run a command that hangs on timeout"])

    assert exit_code == 0
    assert len(holder["client"].calls) == 2
    captured = capsys.readouterr()
    assert captured.out.strip() == "unclean timeout handled"
    assert captured.err == ""
