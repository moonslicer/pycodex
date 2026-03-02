from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pycodex.__main__ as main_module
import pytest
from pycodex.core.config import Config
from pycodex.core.model_client import Completed, OutputItemDone, OutputTextDelta

pytestmark = pytest.mark.e2e


def _tool_payloads(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for item in messages:
        if item.get("role") != "tool":
            continue
        content = item.get("content")
        assert isinstance(content, str)
        payload = json.loads(content)
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def test_cli_e2e_multi_step_tool_loop(
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
            _ = instructions
            tool_names = {
                str(spec["function"].get("name"))
                for spec in tools
                if isinstance(spec, dict)
                and spec.get("type") == "function"
                and isinstance(spec.get("function"), dict)
            }
            assert {"write_file", "read_file"} <= tool_names
            self.calls.append([dict(message) for message in messages])

            if len(self.calls) == 1:
                yield OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "write_file",
                        "arguments": '{"file_path":"note.txt","content":"hello"}',
                        "call_id": "call_write",
                    }
                )
                yield Completed(response_id="resp_write")
                return

            if len(self.calls) == 2:
                write_payload = _tool_payloads(self.calls[1])
                assert len(write_payload) == 1
                assert write_payload[0]["success"] is True
                assert write_payload[0]["body"]["path"] == str(tmp_path / "note.txt")
                yield OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "read_file",
                        "arguments": '{"file_path":"note.txt"}',
                        "call_id": "call_read",
                    }
                )
                yield Completed(response_id="resp_read")
                return

            assert len(self.calls) == 3
            payloads = _tool_payloads(self.calls[2])
            assert len(payloads) == 2
            assert payloads[1]["success"] is True
            assert isinstance(payloads[1]["body"], str)
            assert payloads[1]["body"].startswith("L1: hello")
            yield OutputTextDelta(delta="multi-step complete")
            yield Completed(response_id="resp_done")

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "ModelClient", _FakeModelClient)

    exit_code = main_module.main(["--approval", "never", "write then read"])

    assert exit_code == 0
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hello"
    assert len(holder["client"].calls) == 3
    captured = capsys.readouterr()
    assert captured.out.strip() == "multi-step complete"
    assert captured.err == ""
