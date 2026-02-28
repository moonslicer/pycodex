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
from uuid import uuid4

from pycodex.approval.policy import ReviewDecision
from pycodex.core.agent import AgentEvent, SupportsModelClient, SupportsToolRouter, run_turn
from pycodex.core.event_adapter import EventAdapter
from pycodex.core.session import Session
from pycodex.protocol.events import ApprovalRequested, ProtocolEvent

_MAX_PENDING_APPROVALS = 100


class SupportsLineReader(Protocol):
    async def readline(self) -> bytes: ...


@dataclass(slots=True)
class _PendingApproval:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: ReviewDecision | None = None


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
    _active_turn_id: str | None = field(default=None, init=False)
    _pending_approvals: dict[str, _PendingApproval] = field(default_factory=dict, init=False)

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
                if protocol_event.type == "turn.started":
                    self._active_turn_id = protocol_event.turn_id
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
            self._active_turn_id = None

    def _handle_approval_response(self, params: dict[str, Any]) -> None:
        request_id = params.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return
        decision = _parse_approval_decision(params.get("decision"))
        if decision is None:
            return
        pending = self._pending_approvals.get(request_id)
        if pending is None:
            sys.stderr.write(
                f"[bridge] approval response for unknown request_id {request_id!r}; ignoring\n"
            )
            return
        if pending.decision is not None:
            return
        pending.decision = decision
        pending.event.set()

    async def request_approval(self, tool: Any, args: dict[str, Any]) -> ReviewDecision:
        if self._active_turn_id is None:
            raise RuntimeError("approval requested outside active turn")

        if len(self._pending_approvals) >= _MAX_PENDING_APPROVALS:
            sys.stderr.write(
                f"[bridge] approval queue full ({_MAX_PENDING_APPROVALS} pending); denying request\n"
            )
            return ReviewDecision.DENIED

        request_id = str(uuid4())
        pending = _PendingApproval()
        self._pending_approvals[request_id] = pending
        tool_name = getattr(tool, "name", None)
        normalized_tool_name = tool_name if isinstance(tool_name, str) and tool_name else "unknown"

        try:
            self._emit_protocol_event(
                ApprovalRequested(
                    thread_id=self._adapter.thread_id,
                    turn_id=self._active_turn_id,
                    request_id=request_id,
                    tool=normalized_tool_name,
                    preview=_render_approval_preview(args),
                )
            )
            await pending.event.wait()
            assert pending.decision is not None
            return pending.decision
        finally:
            self._pending_approvals.pop(request_id, None)

    def _handle_interrupt(self) -> None:
        if self._active_turn is not None and not self._active_turn.done():
            self._active_turn.cancel()

    def _emit_protocol_event(self, event: ProtocolEvent) -> None:
        if self.emit_event is not None:
            self.emit_event(event)
            return

        sys.stdout.write(f"{event.model_dump_json()}\n")
        sys.stdout.flush()


def _parse_approval_decision(raw_decision: Any) -> ReviewDecision | None:
    if raw_decision == ReviewDecision.APPROVED.value:
        return ReviewDecision.APPROVED
    if raw_decision == ReviewDecision.DENIED.value:
        return ReviewDecision.DENIED
    if raw_decision == ReviewDecision.APPROVED_FOR_SESSION.value:
        return ReviewDecision.APPROVED_FOR_SESSION
    if raw_decision == ReviewDecision.ABORT.value:
        return ReviewDecision.ABORT
    return None


def _render_approval_preview(args: dict[str, Any]) -> str:
    # Strict redaction: expose only shape metadata, never argument values.
    preview = {
        "arg_count": len(args),
        "arg_keys": sorted(args.keys()),
    }
    return json.dumps(preview, sort_keys=True, ensure_ascii=True)
