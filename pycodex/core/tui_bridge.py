"""Async JSON-RPC bridge for TUI mode."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

from pycodex.core.agent import AgentEvent, SupportsModelClient, SupportsToolRouter, run_turn
from pycodex.core.event_adapter import EventAdapter
from pycodex.core.session import Session
from pycodex.protocol.events import ProtocolEvent


class SupportsLineReader(Protocol):
    async def readline(self) -> bytes: ...


@dataclass(slots=True)
class TuiBridge:
    """Handle stdin JSON-RPC commands and emit JSONL protocol events."""

    session: Session
    model_client: SupportsModelClient
    tool_router: SupportsToolRouter
    cwd: Path
    emit_event: Callable[[ProtocolEvent], None] | None = None
    _adapter: EventAdapter = field(default_factory=EventAdapter, init=False)
    _active_turn: asyncio.Task[None] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._emit_protocol_event(self._adapter.start_thread())

    async def run(self, *, reader: SupportsLineReader | None = None) -> None:
        """Run until stdin EOF, handling one JSON-RPC command per line."""
        stream = reader if reader is not None else await self._connect_stdin()

        while True:
            line = await stream.readline()
            if not line:
                break
            await self._handle_line(line.decode("utf-8", errors="replace").strip())

        # Cancel on EOF so bridge shutdown cannot hang on in-flight work.
        if self._active_turn is not None and not self._active_turn.done():
            self._active_turn.cancel()
            with suppress(asyncio.CancelledError):
                await self._active_turn

    async def _connect_stdin(self) -> SupportsLineReader:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, cast(Any, sys.stdin))
        return reader

    async def _handle_line(self, line: str) -> None:
        if not line:
            return

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return

        if not isinstance(payload, dict):
            return

        method = payload.get("method")
        if not isinstance(method, str):
            return

        raw_params = payload.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}

        if method == "user.input":
            text = params.get("text")
            if not isinstance(text, str):
                return
            await self._handle_user_input(text)
            return

        if method == "approval.response":
            self._handle_approval_response(params)
            return

        if method == "interrupt":
            self._handle_interrupt()

    async def _handle_user_input(self, text: str) -> None:
        if self._active_turn is not None and not self._active_turn.done():
            return

        self._active_turn = asyncio.create_task(self._run_turn(text))

    async def _run_turn(self, text: str) -> None:
        def on_event(event: AgentEvent) -> None:
            for protocol_event in self._adapter.on_agent_event(event):
                self._emit_protocol_event(protocol_event)

        try:
            await run_turn(
                session=self.session,
                model_client=self.model_client,
                tool_router=self.tool_router,
                cwd=self.cwd,
                user_input=text,
                on_event=on_event,
            )
        except asyncio.CancelledError:
            self._emit_protocol_event(self._adapter.turn_failed("interrupted"))
        except Exception as exc:
            self._emit_protocol_event(self._adapter.turn_failed(exc))
        finally:
            self._active_turn = None

    def _handle_approval_response(self, params: dict[str, Any]) -> None:
        # T5 baseline: parse and safely ignore until approval.request flow is added.
        request_id = params.get("request_id")
        decision = params.get("decision")
        if not isinstance(request_id, str) or not request_id:
            return
        if decision not in {"approved", "denied", "approved_for_session", "abort"}:
            return

    def _handle_interrupt(self) -> None:
        if self._active_turn is not None and not self._active_turn.done():
            self._active_turn.cancel()

    def _emit_protocol_event(self, event: ProtocolEvent) -> None:
        if self.emit_event is not None:
            self.emit_event(event)
            return

        sys.stdout.write(f"{event.model_dump_json()}\n")
        sys.stdout.flush()
