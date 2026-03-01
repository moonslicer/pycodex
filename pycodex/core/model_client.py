"""Async model streaming client with typed response events."""

from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pycodex.core.config import Config
from pycodex.core.session import PromptItem

_MAX_STREAM_ATTEMPTS = 2
_TRANSIENT_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
_TRANSIENT_ERROR_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "RateLimitError",
    "InternalServerError",
}


class ModelClientError(RuntimeError):
    """Base exception for model client failures."""


class ModelClientSetupError(ModelClientError):
    """Raised when model client initialization is invalid or unavailable."""


class ModelClientStreamError(ModelClientError):
    """Raised when model streaming cannot complete."""


@dataclass(slots=True, frozen=True)
class OutputTextDelta:
    """Incremental text chunk from model output."""

    delta: str
    type: Literal["output_text_delta"] = "output_text_delta"
    item_id: str | None = None
    output_index: int | None = None


@dataclass(slots=True, frozen=True)
class OutputItemDone:
    """Completed output item, including tool-call items."""

    item: dict[str, Any]
    type: Literal["output_item_done"] = "output_item_done"


@dataclass(slots=True, frozen=True)
class Completed:
    """Final event emitted when the response stream completes."""

    type: Literal["completed"] = "completed"
    response_id: str | None = None
    usage: dict[str, int] | None = None


ResponseEvent = OutputTextDelta | OutputItemDone | Completed
OpenAIFactory = Callable[[Config], Any]


class ModelClient:
    """Thin transport client that streams typed response events."""

    def __init__(
        self,
        config: Config,
        *,
        openai_factory: OpenAIFactory | None = None,
    ) -> None:
        self._config = config
        self._openai_factory = openai_factory or _default_openai_factory
        self._client: Any | None = None

    async def stream(
        self,
        messages: list[PromptItem],
        tools: list[dict[str, Any]],
        instructions: str = "",
    ) -> AsyncIterator[ResponseEvent]:
        """Stream model output as typed events with a single transient retry."""
        for attempt in range(1, _MAX_STREAM_ATTEMPTS + 1):
            emitted_any = False
            try:
                async for event in self._stream_once(
                    messages=messages,
                    tools=tools,
                    instructions=instructions,
                ):
                    emitted_any = True
                    yield event
                return
            except ModelClientSetupError:
                raise
            except ModelClientStreamError:
                raise
            except Exception as exc:  # pragma: no cover - defensive boundary
                is_retryable = (
                    attempt < _MAX_STREAM_ATTEMPTS and not emitted_any and _is_transient_error(exc)
                )
                if is_retryable:
                    continue
                message = _describe_exception(exc)
                raise ModelClientStreamError(
                    f"Model stream failed after {attempt} attempt(s): {message}"
                ) from exc

    async def _stream_once(
        self,
        *,
        messages: list[PromptItem],
        tools: list[dict[str, Any]],
        instructions: str,
    ) -> AsyncIterator[ResponseEvent]:
        client = self._get_client()
        responses = getattr(client, "responses", None)
        if responses is None or not hasattr(responses, "create"):
            raise ModelClientSetupError("OpenAI client is missing responses.create")

        input_items = _convert_prompt_to_responses_input(messages)
        normalized_tools = _normalize_tools_for_responses(tools)
        create_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "input": input_items,
            "tools": normalized_tools,
            "stream": True,
        }
        if instructions:
            create_kwargs["instructions"] = instructions

        stream = await responses.create(**create_kwargs)
        if not hasattr(stream, "__aiter__"):
            raise ModelClientStreamError(
                "responses.create(stream=True) did not return an async stream"
            )

        try:
            async for raw_event in stream:
                mapped = _map_response_event(raw_event)
                if mapped is not None:
                    yield mapped
        finally:
            close = getattr(stream, "aclose", None)
            if callable(close):
                await _maybe_await(close())

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                self._client = self._openai_factory(self._config)
            except Exception as exc:  # pragma: no cover - setup boundary
                message = _describe_exception(exc)
                raise ModelClientSetupError(
                    f"Failed to initialize OpenAI client: {message}"
                ) from exc
        return self._client


def _default_openai_factory(config: Config) -> Any:
    try:
        module = importlib.import_module("openai")
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ModelClientSetupError(
            "openai package is required; install openai>=1.0 to use ModelClient"
        ) from exc

    async_openai = getattr(module, "AsyncOpenAI", None)
    if async_openai is None:
        raise ModelClientSetupError("openai package does not expose AsyncOpenAI")

    return async_openai(
        api_key=config.api_key,
        base_url=config.api_base_url,
    )


def _map_response_event(raw_event: Any) -> ResponseEvent | None:
    event_type = _to_optional_str(_event_get(raw_event, "type"))
    if event_type in {"response.failed", "response.error", "error"}:
        message = _extract_stream_error_message(raw_event)
        raise ModelClientStreamError(f"Model stream event failed: {message}")

    if event_type == "response.output_text.delta":
        delta = _to_optional_str(_event_get(raw_event, "delta")) or ""
        return OutputTextDelta(
            delta=delta,
            item_id=_to_optional_str(_event_get(raw_event, "item_id")),
            output_index=_to_optional_int(_event_get(raw_event, "output_index")),
        )

    if event_type == "response.output_item.done":
        item = _event_get(raw_event, "item")
        if item is None:
            item = _event_get(raw_event, "output_item")
        return OutputItemDone(item=_normalize_item(item))

    if event_type == "response.completed":
        response = _event_get(raw_event, "response")
        response_id = _to_optional_str(_event_get(response, "id"))
        return Completed(response_id=response_id, usage=_extract_usage(response))

    return None


def _convert_prompt_to_responses_input(messages: list[PromptItem]) -> list[dict[str, Any]]:
    input_items: list[dict[str, Any]] = []
    for message in messages:
        payload = dict(message)
        item_type = _to_optional_str(payload.get("type"))
        role = _to_optional_str(payload.get("role"))
        content = payload.get("content", "")

        if item_type == "function_call":
            call_id = _to_optional_str(payload.get("call_id"))
            name = _to_optional_str(payload.get("name"))
            arguments_raw = payload.get("arguments", "{}")
            if call_id is None or name is None:
                continue
            if isinstance(arguments_raw, str):
                arguments = arguments_raw
            elif isinstance(arguments_raw, dict):
                arguments = json.dumps(arguments_raw, ensure_ascii=True)
            else:
                arguments = "{}"

            input_items.append(
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": arguments,
                }
            )
            continue

        if role == "tool":
            call_id = _to_optional_str(payload.get("tool_call_id"))
            if call_id is None:
                continue
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": str(content),
                }
            )
            continue

        if role in {"user", "assistant", "system"}:
            input_items.append(
                {
                    "role": role,
                    "content": str(content),
                }
            )

    return input_items


def _normalize_tools_for_responses(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    for tool in tools:
        payload = dict(tool)
        if payload.get("type") != "function":
            normalized.append(payload)
            continue

        function_payload = payload.get("function")
        if isinstance(function_payload, dict):
            merged = dict(payload)
            merged.pop("function", None)
            merged.update(function_payload)
            normalized.append(merged)
            continue

        normalized.append(payload)

    return normalized


def _event_get(container: Any, key: str) -> Any:
    if container is None:
        return None
    if isinstance(container, dict):
        return container.get(key)
    return getattr(container, key, None)


def _normalize_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if item is None:
        return {}

    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        if isinstance(dumped, dict):
            return dumped

    as_dict = getattr(item, "__dict__", None)
    if isinstance(as_dict, dict):
        return dict(as_dict)

    return {"value": str(item)}


def _to_optional_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _to_optional_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _extract_stream_error_message(raw_event: Any) -> str:
    error = _event_get(raw_event, "error")
    if error is not None:
        message = _to_optional_str(_event_get(error, "message"))
        code = _to_optional_str(_event_get(error, "code"))
        if message and code:
            return f"{code}: {message}"
        if message:
            return message
        if code:
            return code
        return str(error)

    fallback = _to_optional_str(_event_get(raw_event, "message"))
    if fallback:
        return fallback

    return "unknown stream failure"


def _extract_usage(response: Any) -> dict[str, int] | None:
    usage = _event_get(response, "usage")
    input_tokens = _to_optional_int(_event_get(usage, "input_tokens"))
    output_tokens = _to_optional_int(_event_get(usage, "output_tokens"))
    if input_tokens is None or output_tokens is None:
        return None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
        return True

    if type(exc).__name__ in _TRANSIENT_ERROR_NAMES:
        return True

    for attr in ("status_code", "status"):
        status = getattr(exc, attr, None)
        if isinstance(status, int) and status in _TRANSIENT_STATUS_CODES:
            return True

    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if isinstance(status, int) and status in _TRANSIENT_STATUS_CODES:
            return True

    cause = exc.__cause__
    if isinstance(cause, Exception):
        return _is_transient_error(cause)

    return False


def _describe_exception(exc: Exception) -> str:
    text = str(exc).strip()
    return text or type(exc).__name__


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
