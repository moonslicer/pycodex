"""Session listing and rollout-resolution helpers shared by CLI and TUI bridge."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pycodex.core.config import Config
from pycodex.core.rollout_recorder import default_sessions_root, resolve_latest_rollout
from pycodex.core.rollout_replay import (
    RolloutReplayError,
    import_legacy_session_json,
    replay_rollout,
)
from pycodex.core.rollout_schema import SessionClosed, validate_rollout_item


@dataclass(frozen=True, slots=True)
class SessionSummaryRecord:
    thread_id: str
    status: Literal["closed", "incomplete"]
    turn_count: int
    token_total: int
    last_user_message: str | None
    date: str
    updated_at: str
    size_bytes: int


_FALLBACK_UPDATED_AT = "1970-01-01T00:00:00Z"


async def resolve_resume_rollout_path(
    *,
    config: Config,
    resume: str,
    sessions_root: Path | None = None,
) -> Path:
    path_candidate = await asyncio.to_thread(lambda: Path(resume).expanduser())
    if await asyncio.to_thread(path_candidate.exists):
        return path_candidate

    resolved_sessions_root = sessions_root or _resolve_sessions_root(config)
    latest = resolve_latest_rollout(resume, root=resolved_sessions_root)
    if latest is not None:
        return latest

    legacy_path = resolved_sessions_root / f"{resume}.json"
    if await asyncio.to_thread(legacy_path.exists):
        return await import_legacy_session_json(
            legacy_path=legacy_path,
            thread_id=resume,
            sessions_root=resolved_sessions_root,
        )

    raise RolloutReplayError(
        code="rollout_not_found",
        message=f"Unable to resolve rollout for {resume!r}.",
    )


def read_session_closed(path: Path) -> SessionClosed | None:
    """Read only the last line of a rollout file and parse a session.closed record."""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            end = f.tell()
            if end == 0:
                return None

            chunk_size = 4096
            buf = b""
            pos = end
            line_start = -1
            line_end = -1
            while pos > 0:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                buf = chunk + buf
                if line_end == -1:
                    stripped = buf.rstrip(b"\r\n")
                    if not stripped:
                        continue
                    line_end = pos + len(stripped)
                nl = buf.rfind(b"\n", 0, line_end - pos)
                if nl == -1:
                    nl = buf.rfind(b"\r", 0, line_end - pos)
                if nl != -1:
                    line_start = pos + nl + 1
                    break
            if line_end == -1:
                return None
            if line_start == -1:
                line_start = 0
            f.seek(line_start)
            last_line = f.read(line_end - line_start).decode("utf-8")
        parsed = json.loads(last_line)
        item = validate_rollout_item(parsed)
        if isinstance(item, SessionClosed):
            return item
        return None
    except Exception:
        return None


def list_sessions(
    *,
    config: Config,
    limit: int | None = None,
    sessions_root: Path | None = None,
) -> list[SessionSummaryRecord]:
    if limit is not None and limit <= 0:
        return []

    resolved_sessions_root = sessions_root or _resolve_sessions_root(config)
    rollout_paths = sorted(
        resolved_sessions_root.glob("rollout-*.jsonl"), key=lambda p: p.name, reverse=True
    )
    records: list[SessionSummaryRecord] = []
    for path in rollout_paths:
        date_token = rollout_date_token(path.name)
        stat_result = _safe_stat(path)
        size_bytes = stat_result.st_size if stat_result is not None else 0
        updated_at_from_stat = (
            _format_iso_utc(stat_result.st_mtime)
            if stat_result is not None
            else _FALLBACK_UPDATED_AT
        )
        session_closed = read_session_closed(path)
        if session_closed is not None:
            token_total = (
                session_closed.token_total.input_tokens + session_closed.token_total.output_tokens
            )
            updated_at = session_closed.closed_at or updated_at_from_stat
            records.append(
                SessionSummaryRecord(
                    thread_id=session_closed.thread_id,
                    status="closed",
                    turn_count=session_closed.turn_count,
                    token_total=token_total,
                    last_user_message=session_closed.last_user_message,
                    date=date_token,
                    updated_at=updated_at,
                    size_bytes=size_bytes,
                )
            )
        else:
            state = replay_rollout(path)
            token_total = (
                state.cumulative_usage["input_tokens"] + state.cumulative_usage["output_tokens"]
            )
            records.append(
                SessionSummaryRecord(
                    thread_id=state.thread_id,
                    status=state.status,
                    turn_count=state.turn_count,
                    token_total=token_total,
                    last_user_message=last_user_message_from_history(state.history),
                    date=date_token,
                    updated_at=updated_at_from_stat,
                    size_bytes=size_bytes,
                )
            )

        if limit is not None and len(records) >= limit:
            return records

    return records


def last_user_message_from_history(history: Sequence[object]) -> str | None:
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content
    return None


def rollout_date_token(filename: str) -> str:
    prefix = "rollout-"
    if not filename.startswith(prefix):
        return "unknown"
    remainder = filename[len(prefix) :]
    return remainder.split("-", 1)[0]


def _safe_stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None


def _format_iso_utc(timestamp_seconds: float) -> str:
    return (
        datetime.fromtimestamp(timestamp_seconds, tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _ensure_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return True


def _resolve_sessions_root(config: Config) -> Path:
    preferred = default_sessions_root()
    if _ensure_directory(preferred):
        return preferred
    fallback = config.cwd / ".pycodex" / "sessions"
    _ensure_directory(fallback)
    sys.stderr.write(
        f"[WARNING] Could not create sessions directory {preferred}; using fallback {fallback}\n"
    )
    return fallback
