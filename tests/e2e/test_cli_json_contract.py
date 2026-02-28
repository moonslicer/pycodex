from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pycodex.__main__ as main_module
import pytest
from pycodex.core.config import Config
from pycodex.core.model_client import Completed, OutputItemDone, OutputTextDelta

pytestmark = pytest.mark.e2e


def test_cli_e2e_json_contract_event_sequence_and_required_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(model="test-model", api_key="test-key", cwd=tmp_path)

    class _FakeModelClient:
        def __init__(self, _config: Config) -> None:
            self.calls: list[list[dict[str, Any]]] = []

        async def stream(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ):
            self.calls.append([dict(message) for message in messages])

            tool_names = {
                str(spec["function"].get("name"))
                for spec in tools
                if isinstance(spec, dict)
                and spec.get("type") == "function"
                and isinstance(spec.get("function"), dict)
            }
            assert "shell" in tool_names

            if len(self.calls) == 1:
                yield OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "shell",
                        "arguments": '{"command":"printf hi"}',
                        "call_id": "call_json_1",
                    }
                )
                yield Completed(response_id="resp_tool")
                return

            assert len(self.calls) == 2
            tool_messages = [msg for msg in messages if msg.get("role") == "tool"]
            assert tool_messages
            yield OutputTextDelta(delta="json mode complete")
            yield Completed(
                response_id="resp_done",
                usage={"input_tokens": 12, "output_tokens": 3},
            )

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "ModelClient", _FakeModelClient)

    exit_code = main_module.main(["--json", "--approval", "never", "run shell then answer"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""

    events = [json.loads(line) for line in captured.out.splitlines()]
    assert [event["type"] for event in events] == [
        "thread.started",
        "turn.started",
        "item.started",
        "item.completed",
        "item.updated",
        "turn.completed",
    ]

    thread_started, turn_started, item_started, item_completed, item_updated, turn_completed = (
        events
    )

    assert {"type", "thread_id"} <= set(thread_started)

    assert {"type", "thread_id", "turn_id"} <= set(turn_started)
    assert turn_started["thread_id"] == thread_started["thread_id"]

    assert {"type", "thread_id", "turn_id", "item_id", "item_kind", "name", "arguments"} <= set(
        item_started
    )
    assert item_started["thread_id"] == thread_started["thread_id"]
    assert item_started["turn_id"] == turn_started["turn_id"]
    assert item_started["item_id"] == "call_json_1"
    assert item_started["item_kind"] == "tool_call"

    assert {"type", "thread_id", "turn_id", "item_id", "item_kind", "content"} <= set(
        item_completed
    )
    assert item_completed["thread_id"] == thread_started["thread_id"]
    assert item_completed["turn_id"] == turn_started["turn_id"]
    assert item_completed["item_id"] == "call_json_1"
    assert item_completed["item_kind"] == "tool_result"

    assert {"type", "thread_id", "turn_id", "item_id", "delta"} <= set(item_updated)
    assert item_updated["thread_id"] == thread_started["thread_id"]
    assert item_updated["turn_id"] == turn_started["turn_id"]
    assert isinstance(item_updated["item_id"], str)
    assert item_updated["item_id"]
    assert item_updated["delta"] == "json mode complete"

    assert {"type", "thread_id", "turn_id", "final_text", "usage"} <= set(turn_completed)
    assert turn_completed["thread_id"] == thread_started["thread_id"]
    assert turn_completed["turn_id"] == turn_started["turn_id"]
    assert turn_completed["final_text"] == "json mode complete"
    assert turn_completed["usage"] == {"input_tokens": 12, "output_tokens": 3}
