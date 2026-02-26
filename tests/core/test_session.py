from __future__ import annotations

from pycodex.core.session import Session


def test_session_starts_with_empty_history() -> None:
    session = Session()
    assert session.to_prompt() == []


def test_append_user_message_adds_user_item() -> None:
    session = Session()
    session.append_user_message("hello")

    assert session.to_prompt() == [{"role": "user", "content": "hello"}]


def test_append_tool_result_adds_tool_item() -> None:
    session = Session()
    session.append_tool_result("call_123", "ok")

    assert session.to_prompt() == [{"role": "tool", "tool_call_id": "call_123", "content": "ok"}]


def test_session_preserves_append_order() -> None:
    session = Session()
    session.append_user_message("first")
    session.append_tool_result("call_1", "result")
    session.append_user_message("second")

    assert session.to_prompt() == [
        {"role": "user", "content": "first"},
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        {"role": "user", "content": "second"},
    ]


def test_to_prompt_returns_detached_copy() -> None:
    session = Session()
    session.append_user_message("original")

    prompt = session.to_prompt()
    prompt.append({"role": "tool", "tool_call_id": "call_x", "content": "mutated"})
    prompt[0]["content"] = "changed"

    assert session.to_prompt() == [{"role": "user", "content": "original"}]
