from __future__ import annotations

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


def test_cli_e2e_on_request_write_file_approved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)
    prompts: list[str] = []
    holder: dict[str, Any] = {}

    class _FakeModelClient:
        def __init__(self, _config: Config) -> None:
            self.calls: list[list[dict[str, Any]]] = []
            holder["client"] = self

        async def stream(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            instructions: str = "",
        ):
            _ = instructions
            tool_names = {
                str(spec["function"].get("name"))
                for spec in tools
                if isinstance(spec, dict)
                and spec.get("type") == "function"
                and isinstance(spec.get("function"), dict)
            }
            assert "write_file" in tool_names
            self.calls.append([dict(message) for message in messages])

            if len(self.calls) == 1:
                yield OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "write_file",
                        "arguments": '{"file_path":"approved.txt","content":"hello world"}',
                        "call_id": "call_write",
                    }
                )
                yield Completed(response_id="resp_tool")
                return

            assert len(self.calls) == 2
            payload = _tool_payload(self.calls[1])
            assert payload["success"] is True
            assert payload["body"]["path"] == str(tmp_path / "approved.txt")
            yield OutputTextDelta(delta="write approved")
            yield Completed(response_id="resp_done")

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "ModelClient", _FakeModelClient)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (prompts.append(prompt), "y")[1],
    )

    exit_code = main_module.main(["--approval", "on-request", "write a file"])

    assert exit_code == 0
    assert (tmp_path / "approved.txt").read_text(encoding="utf-8") == "hello world"
    assert prompts and "Approve tool 'write_file'" in prompts[0]
    assert holder["client"].calls and len(holder["client"].calls) == 2
    captured = capsys.readouterr()
    assert captured.out.strip() == "write approved"
    assert captured.err == ""


def test_cli_e2e_on_request_write_file_denied(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)
    holder: dict[str, Any] = {}

    class _FakeModelClient:
        def __init__(self, _config: Config) -> None:
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
                        "name": "write_file",
                        "arguments": '{"file_path":"denied.txt","content":"nope"}',
                        "call_id": "call_write_denied",
                    }
                )
                yield Completed(response_id="resp_tool")
                return

            assert len(self.calls) == 2
            payload = _tool_payload(self.calls[1])
            assert payload["success"] is False
            assert payload["error"]["code"] == "denied"
            assert payload["body"] == "Operation denied by user."
            yield OutputTextDelta(delta="denial handled")
            yield Completed(response_id="resp_done")

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "ModelClient", _FakeModelClient)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    exit_code = main_module.main(["--approval", "on-request", "try writing"])

    assert exit_code == 0
    assert not (tmp_path / "denied.txt").exists()
    assert len(holder["client"].calls) == 2
    captured = capsys.readouterr()
    assert captured.out.strip() == "denial handled"
    assert captured.err == ""


def test_cli_e2e_on_request_write_file_abort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)
    holder: dict[str, Any] = {}

    class _FakeModelClient:
        def __init__(self, _config: Config) -> None:
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
            assert len(self.calls) == 1
            yield OutputItemDone(
                item={
                    "type": "function_call",
                    "name": "write_file",
                    "arguments": '{"file_path":"aborted.txt","content":"stop"}',
                    "call_id": "call_write_abort",
                }
            )
            yield Completed(response_id="resp_tool")

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "ModelClient", _FakeModelClient)
    monkeypatch.setattr("builtins.input", lambda _prompt: "a")

    exit_code = main_module.main(["--approval", "on-request", "write and abort"])

    assert exit_code == 0
    assert not (tmp_path / "aborted.txt").exists()
    assert len(holder["client"].calls) == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == "Aborted by user."
    assert captured.err == ""
