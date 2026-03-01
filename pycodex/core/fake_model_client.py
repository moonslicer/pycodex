"""Deterministic local model client for offline verification flows."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from pycodex.core.config import Config
from pycodex.core.model_client import Completed, OutputItemDone, OutputTextDelta, ResponseEvent
from pycodex.core.session import PromptItem

_LONG_RESPONSE_CHUNKS = 40
_LONG_RESPONSE_DELAY_S = 0.2
_MUTATION_TRIGGER_PHRASE = "create a file for approval test"


class FakeModelClient:
    """Simple deterministic model behavior used by local verification mode."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._call_counter = 0

    async def stream(
        self,
        messages: list[PromptItem],
        tools: list[dict[str, object]],
        instructions: str = "",
    ) -> AsyncIterator[ResponseEvent]:
        _ = tools, instructions, self._config
        latest_tool_output = _latest_tool_output(messages)
        if latest_tool_output is not None:
            yield OutputTextDelta(delta="Done. Tool execution completed.")
            yield Completed(usage={"input_tokens": 12, "output_tokens": 6})
            return

        user_text = _latest_user_text(messages).lower()
        if _is_mutation_prompt(user_text):
            self._call_counter += 1
            file_path = "verification-output.txt"
            content = "created by PYCODEX_FAKE_MODEL verification flow"
            yield OutputItemDone(
                item={
                    "type": "function_call",
                    "call_id": f"call_{self._call_counter}",
                    "name": "write_file",
                    "arguments": json.dumps(
                        {"file_path": file_path, "content": content},
                        ensure_ascii=True,
                    ),
                }
            )
            yield Completed(usage={"input_tokens": 18, "output_tokens": 4})
            return

        if "interrupt" in user_text:
            for index in range(_LONG_RESPONSE_CHUNKS):
                await asyncio.sleep(_LONG_RESPONSE_DELAY_S)
                yield OutputTextDelta(delta=f"chunk-{index + 1} ")
            yield Completed(usage={"input_tokens": 20, "output_tokens": 50})
            return

        if "2+2" in user_text or "2 + 2" in user_text:
            yield OutputTextDelta(delta="4")
            yield Completed(usage={"input_tokens": 10, "output_tokens": 1})
            return

        yield OutputTextDelta(delta="FAKE_MODEL_OK")
        yield Completed(usage={"input_tokens": 8, "output_tokens": 2})


def _latest_user_text(messages: list[PromptItem]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


def _latest_tool_output(messages: list[PromptItem]) -> str | None:
    if not messages:
        return None
    message = messages[-1]
    if message.get("role") != "tool":
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    return None


def _is_mutation_prompt(user_text: str) -> bool:
    # Keep offline mutation behavior deterministic and opt-in for verification.
    normalized = " ".join(user_text.lower().split())
    return normalized == _MUTATION_TRIGGER_PHRASE
