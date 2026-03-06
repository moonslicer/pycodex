from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pycodex.core.config import Config
from pycodex.core.rollout_recorder import RolloutRecorder, build_rollout_path
from pycodex.core.session import MAX_TOOL_RESULT_CHARS, Session


def test_session_starts_with_empty_history() -> None:
    session = Session()
    assert session.to_prompt() == []


def test_append_user_message_adds_user_item() -> None:
    session = Session()
    session.append_user_message("hello")

    assert session.to_prompt() == [{"role": "user", "content": "hello"}]


def test_append_assistant_message_adds_assistant_item() -> None:
    session = Session()
    session.append_assistant_message("hello from assistant")

    assert session.to_prompt() == [{"role": "assistant", "content": "hello from assistant"}]


def test_append_system_message_adds_system_item() -> None:
    session = Session()
    session.append_system_message("policy context")

    assert session.to_prompt() == [{"role": "system", "content": "policy context"}]


def test_append_tool_result_adds_tool_item() -> None:
    session = Session()
    session.append_tool_result("call_123", "ok")

    assert session.to_prompt() == [{"role": "tool", "tool_call_id": "call_123", "content": "ok"}]


def test_append_function_call_adds_function_call_item() -> None:
    session = Session()
    session.append_function_call(
        call_id="call_1",
        name="read_file",
        arguments={"file_path": "README.md"},
    )

    assert session.to_prompt() == [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"file_path": "README.md"}',
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "aborted"},
    ]


def test_session_preserves_append_order() -> None:
    session = Session()
    session.append_user_message("first")
    session.append_assistant_message("assistant before tool")
    session.append_function_call(call_id="call_1", name="read_file", arguments="{}")
    session.append_tool_result("call_1", "result")
    session.append_user_message("second")

    assert session.to_prompt() == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "assistant before tool"},
        {"type": "function_call", "call_id": "call_1", "name": "read_file", "arguments": "{}"},
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        {"role": "user", "content": "second"},
    ]


def test_to_prompt_appends_missing_tool_output_for_unpaired_function_call() -> None:
    session = Session()
    session.append_user_message("first")
    session.append_function_call(call_id="call_missing", name="read_file", arguments="{}")
    session.append_user_message("second")

    assert session.to_prompt() == [
        {"role": "user", "content": "first"},
        {
            "type": "function_call",
            "call_id": "call_missing",
            "name": "read_file",
            "arguments": "{}",
        },
        {"role": "tool", "tool_call_id": "call_missing", "content": "aborted"},
        {"role": "user", "content": "second"},
    ]


def test_to_prompt_inserts_missing_outputs_after_each_unmatched_call() -> None:
    session = Session()
    session.append_function_call(call_id="call_1", name="read_file", arguments="{}")
    session.append_user_message("middle")
    session.append_function_call(call_id="call_2", name="shell", arguments='{"command":"pwd"}')
    session.append_user_message("tail")

    assert session.to_prompt() == [
        {"type": "function_call", "call_id": "call_1", "name": "read_file", "arguments": "{}"},
        {"role": "tool", "tool_call_id": "call_1", "content": "aborted"},
        {"role": "user", "content": "middle"},
        {
            "type": "function_call",
            "call_id": "call_2",
            "name": "shell",
            "arguments": '{"command":"pwd"}',
        },
        {"role": "tool", "tool_call_id": "call_2", "content": "aborted"},
        {"role": "user", "content": "tail"},
    ]


def test_to_prompt_returns_detached_copy() -> None:
    session = Session()
    session.append_user_message("original")

    prompt = session.to_prompt()
    prompt.append({"role": "tool", "tool_call_id": "call_x", "content": "mutated"})
    prompt[0]["content"] = "changed"

    assert session.to_prompt() == [{"role": "user", "content": "original"}]


def test_prepend_items_places_items_before_existing_history() -> None:
    session = Session()
    session.append_user_message("user message")
    session.prepend_items(
        [
            {"role": "system", "content": "policy"},
            {"role": "system", "content": "project docs"},
        ]
    )

    assert session.to_prompt() == [
        {"role": "system", "content": "policy"},
        {"role": "system", "content": "project docs"},
        {"role": "user", "content": "user message"},
    ]


@pytest.mark.asyncio
async def test_session_context_manager_closes_rollout_on_exit(tmp_path):
    config = Config(model="gpt-4.1-mini", api_key="test", cwd=tmp_path)
    session = Session(config=config)
    path = build_rollout_path(session.thread_id, root=tmp_path)
    session.configure_rollout_recorder(recorder=RolloutRecorder(path=path), path=path)

    async with session:
        pass

    assert session._rollout_closed is True


@pytest.mark.asyncio
async def test_session_context_manager_does_not_mask_body_exception(tmp_path):
    config = Config(model="gpt-4.1-mini", api_key="test", cwd=tmp_path)
    session = Session(config=config)

    mock = AsyncMock(side_effect=RuntimeError("cleanup error"))
    with patch.object(Session, "close_rollout", mock):
        with pytest.raises(ValueError, match="body error"):
            async with session:
                raise ValueError("body error")


@pytest.mark.asyncio
async def test_session_context_manager_propagates_cleanup_error_when_body_succeeds(tmp_path):
    config = Config(model="gpt-4.1-mini", api_key="test", cwd=tmp_path)
    session = Session(config=config)

    mock = AsyncMock(side_effect=RuntimeError("cleanup error"))
    with patch.object(Session, "close_rollout", mock):
        with pytest.raises(RuntimeError, match="cleanup error"):
            async with session:
                pass


def test_append_tool_result_truncates_oversized_content() -> None:
    session = Session()
    oversized = "x" * (MAX_TOOL_RESULT_CHARS + 5)

    session.append_tool_result("call_1", oversized)
    tool_item = session.to_prompt()[0]

    assert tool_item["role"] == "tool"
    assert tool_item["tool_call_id"] == "call_1"
    assert isinstance(tool_item["content"], str)
    assert len(tool_item["content"]) > MAX_TOOL_RESULT_CHARS
    assert tool_item["content"].endswith("\n...[truncated by session history cap]")
