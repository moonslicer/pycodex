"""Async JSON-RPC bridge for TUI mode."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

from pycodex.approval.policy import ReviewDecision
from pycodex.core.agent import AgentEvent, SupportsModelClient, SupportsToolRouter, run_turn
from pycodex.core.config import Config
from pycodex.core.event_adapter import EventAdapter
from pycodex.core.rollout_recorder import RolloutRecorder, build_rollout_path
from pycodex.core.rollout_replay import replay_rollout
from pycodex.core.session import PromptItem, Session
from pycodex.core.session_store import (
    list_sessions,
    resolve_resume_rollout_path,
    resolve_sessions_root,
)
from pycodex.protocol.events import (
    ApprovalRequested,
    HydratedTurn,
    ProtocolEvent,
    SessionError,
    SessionHydrated,
    SessionListed,
    SessionStatus,
    SessionSummary,
    SlashBlocked,
    SlashUnknown,
)

_MAX_PENDING_APPROVALS = 100
_MAX_SHELL_COMMAND_PREVIEW_CHARS = 240
_SUMMARY_BLOCK_MARKER = "[compaction.summary.v1]"
logger = logging.getLogger(__name__)

_SENSITIVE_ENV_KEY_PATTERN = re.compile(
    r"(?i)(?:token|secret|password|passwd|api[_-]?key|auth(?:orization)?|cookie)"
)
_SENSITIVE_FLAG_VALUE_PATTERN = re.compile(
    r"(?i)(--?(?:token|secret|password|passwd|api[_-]?key|auth(?:orization)?|cookie)\s*=?\s*)(\S+)"
)
_SENSITIVE_ENV_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b([A-Za-z_][A-Za-z0-9_]*(?:token|secret|password|passwd|api[_-]?key|auth(?:orization)?|cookie)[A-Za-z0-9_]*)=(\S+)"
)
_SENSITIVE_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+\S+")


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
    _adapter: EventAdapter = field(init=False)
    _active_turn: asyncio.Task[None] | None = field(default=None, init=False)
    _active_turn_id: str | None = field(default=None, init=False)
    _pending_approvals: dict[str, _PendingApproval] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._adapter = EventAdapter(thread_id=self.session.thread_id)
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

        if method == "session.resume":
            await self._handle_session_resume(params)
            return

        if method == "session.new":
            await self._handle_session_new()
            return

        if method == "interrupt":
            self._handle_interrupt()

    async def _handle_user_input(self, text: str) -> None:
        if text.startswith("/"):
            await self._handle_slash_command(text)
            return
        if self._active_turn is not None and not self._active_turn.done():
            return

        self._active_turn = asyncio.create_task(self._run_turn(text))

    async def _handle_slash_command(self, text: str) -> None:
        remainder = text[1:].strip()
        command = remainder.split(maxsplit=1)[0].lower() if remainder else ""
        if command == "status":
            await self._slash_status()
            return
        if command == "resume":
            await self._slash_resume()
            return
        if command == "new":
            await self._slash_new()
            return
        self._emit_protocol_event(SlashUnknown(command=command))

    async def _slash_status(self) -> None:
        usage = self.session.cumulative_usage()
        context_window_tokens = (
            self.session.config.compaction_context_window_tokens
            if self.session.config is not None
            else 0
        )
        self._emit_protocol_event(
            SessionStatus(
                thread_id=self.session.thread_id,
                turn_count=self.session.completed_turn_count(),
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                context_window_tokens=context_window_tokens,
                compaction_count=self.session.compaction_count(),
            )
        )

    async def _slash_resume(self) -> None:
        if self._turn_is_active():
            self._emit_protocol_event(SlashBlocked(command="resume", reason="active_turn"))
            return
        try:
            config = self._require_session_config()
            records = list_sessions(config=config, limit=500)
            summaries = [
                SessionSummary(
                    thread_id=record.thread_id,
                    status=record.status,
                    turn_count=record.turn_count,
                    token_total=record.token_total,
                    last_user_message=record.last_user_message,
                    date=record.date,
                    updated_at=record.updated_at,
                    size_bytes=record.size_bytes,
                )
                for record in records
                if record.thread_id != self.session.thread_id
            ]
            self._emit_protocol_event(SessionListed(sessions=summaries))
        except Exception as exc:
            self._emit_protocol_event(SessionError(operation="list", message=_error_message(exc)))

    async def _slash_new(self) -> None:
        if self._turn_is_active():
            self._emit_protocol_event(SlashBlocked(command="new", reason="active_turn"))
            return
        try:
            new_session = self._create_new_session()
            await self._activate_session(new_session)
        except Exception as exc:
            self._emit_protocol_event(SessionError(operation="new", message=_error_message(exc)))

    async def _handle_session_resume(self, params: dict[str, Any]) -> None:
        if self._turn_is_active():
            self._emit_protocol_event(
                SessionError(
                    operation="resume",
                    message="Cannot resume while a turn is active.",
                )
            )
            return

        thread_id = params.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            self._emit_protocol_event(
                SessionError(operation="resume", message="session.resume requires a thread_id.")
            )
            return
        if thread_id == self.session.thread_id:
            self._emit_protocol_event(
                SessionError(
                    operation="resume",
                    message="Cannot resume the currently active thread.",
                )
            )
            return

        try:
            config = self._require_session_config()
            rollout_path = await resolve_resume_rollout_path(
                config=config,
                resume=thread_id,
                sessions_root=resolve_sessions_root(config),
            )
            replay_state = replay_rollout(rollout_path)
            hydrated_turns = _build_hydrated_turns(replay_state.display_history)
            resumed_session = Session(config=config, thread_id=replay_state.thread_id)
            resumed_session.restore_from_rollout(
                history=replay_state.history,
                cumulative_usage=replay_state.cumulative_usage,
                turn_count=replay_state.turn_count,
                initial_context_injected=replay_state.initial_context_injected,
            )
            resumed_session.configure_rollout_recorder(
                recorder=RolloutRecorder(path=rollout_path),
                path=rollout_path,
            )
            await self._activate_session(resumed_session)
            self._emit_protocol_event(
                SessionHydrated(
                    thread_id=resumed_session.thread_id,
                    turns=hydrated_turns,
                )
            )
        except Exception as exc:
            self._emit_protocol_event(SessionError(operation="resume", message=_error_message(exc)))

    async def _handle_session_new(self) -> None:
        if self._turn_is_active():
            self._emit_protocol_event(
                SessionError(
                    operation="new",
                    message="Cannot create a new session while a turn is active.",
                )
            )
            return
        try:
            new_session = self._create_new_session()
            await self._activate_session(new_session)
        except Exception as exc:
            self._emit_protocol_event(SessionError(operation="new", message=_error_message(exc)))

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
            logger.warning("approval response for unknown request_id %r; ignoring", request_id)
            return
        if pending.decision is not None:
            return
        pending.decision = decision
        pending.event.set()

    async def request_approval(self, tool: Any, args: dict[str, Any]) -> ReviewDecision:
        if self._active_turn_id is None:
            raise RuntimeError("approval requested outside active turn")

        if len(self._pending_approvals) >= _MAX_PENDING_APPROVALS:
            logger.warning(
                "approval queue full (%d pending); denying request", _MAX_PENDING_APPROVALS
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
                    preview=_render_approval_preview(tool_name=normalized_tool_name, args=args),
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

    def _turn_is_active(self) -> bool:
        return self._active_turn is not None and not self._active_turn.done()

    async def _activate_session(self, new_session: Session) -> None:
        if self._current_session_has_local_activity():
            await self.session.close_rollout()
        self._pending_approvals.clear()
        self.session = new_session
        self._adapter = EventAdapter(thread_id=new_session.thread_id)
        self._emit_protocol_event(self._adapter.start_thread())

    def _current_session_has_local_activity(self) -> bool:
        return self.session.last_user_message() is not None or self.session.rollout_meta_written()

    def _require_session_config(self) -> Config:
        config = self.session.config
        if config is None:
            raise RuntimeError("Session config is not available.")
        return config

    def _create_new_session(self) -> Session:
        config = self._require_session_config()
        new_session = Session(config=config)
        self._configure_rollout_persistence(new_session, config=config)
        return new_session

    def _configure_rollout_persistence(
        self,
        session: Session,
        *,
        config: Config,
    ) -> None:
        sessions_root = resolve_sessions_root(config)
        path = build_rollout_path(session.thread_id, root=sessions_root)
        session.configure_rollout_recorder(
            recorder=RolloutRecorder(path=path),
            path=path,
        )


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


def _build_hydrated_turns(history: list[PromptItem]) -> list[HydratedTurn]:
    turns: list[HydratedTurn] = []
    current_user: str | None = None
    assistant_messages: list[str] = []
    current_compaction_summary: str | None = None
    pending_compaction_summary: str | None = None

    def append_current_turn() -> None:
        nonlocal current_compaction_summary, current_user, assistant_messages
        if current_user is None:
            return
        turns.append(
            HydratedTurn(
                turn_id=f"hydrated_{len(turns) + 1}",
                user_text=current_user,
                assistant_text="\n\n".join(assistant_messages),
                compaction_summary=current_compaction_summary,
            )
        )
        current_user = None
        assistant_messages = []
        current_compaction_summary = None

    for item in history:
        role = item.get("role")
        content = item.get("content")
        text = content if isinstance(content, str) else ""
        if role == "system" and _SUMMARY_BLOCK_MARKER in text:
            pending_compaction_summary = text
            continue
        if role == "user":
            append_current_turn()
            current_user = text
            current_compaction_summary = pending_compaction_summary
            pending_compaction_summary = None
            continue
        if role == "assistant" and current_user is not None:
            assistant_messages.append(text)

    append_current_turn()
    return turns


def _error_message(exc: Exception) -> str:
    return str(exc).strip() or type(exc).__name__


def _render_approval_preview(*, tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "shell":
        return _render_shell_approval_preview(args=args)

    # Default strict redaction for non-shell tools: expose only shape metadata.
    preview = {
        "arg_count": len(args),
        "arg_keys": sorted(args.keys()),
    }
    return json.dumps(preview, sort_keys=True, ensure_ascii=True)


def _render_shell_approval_preview(*, args: dict[str, Any]) -> str:
    preview: dict[str, Any] = {
        "arg_count": len(args),
        "arg_keys": sorted(args.keys()),
        "mode": "shell",
    }

    command = args.get("command")
    if isinstance(command, str) and command.strip():
        preview["command_preview"] = _sanitize_shell_command_preview(command)

    timeout_ms = args.get("timeout_ms")
    if isinstance(timeout_ms, int) and not isinstance(timeout_ms, bool) and timeout_ms > 0:
        preview["timeout_ms"] = timeout_ms

    return json.dumps(preview, sort_keys=True, ensure_ascii=True)


def _sanitize_shell_command_preview(command: str) -> str:
    compact = " ".join(command.strip().split())
    if not compact:
        return compact

    preview = _SENSITIVE_ENV_ASSIGNMENT_PATTERN.sub(r"\1=***REDACTED***", compact)
    preview = _SENSITIVE_FLAG_VALUE_PATTERN.sub(r"\1***REDACTED***", preview)
    preview = _SENSITIVE_BEARER_PATTERN.sub("Bearer ***REDACTED***", preview)
    preview = _redact_sensitive_env_prefix_assignments(preview)

    if len(preview) <= _MAX_SHELL_COMMAND_PREVIEW_CHARS:
        return preview
    return f"{preview[:_MAX_SHELL_COMMAND_PREVIEW_CHARS]}..."


def _redact_sensitive_env_prefix_assignments(command: str) -> str:
    tokens = command.split(" ")
    if len(tokens) == 0:
        return command

    redacted_tokens: list[str] = []
    for token in tokens:
        if "=" not in token:
            redacted_tokens.append(token)
            continue

        key, _, _value = token.partition("=")
        if _SENSITIVE_ENV_KEY_PATTERN.search(key) is None:
            redacted_tokens.append(token)
            continue

        redacted_tokens.append(f"{key}=***REDACTED***")

    return " ".join(redacted_tokens)
