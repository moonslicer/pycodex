"""Replay and legacy-import helpers for session rollout JSONL ledgers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from pycodex.core.rollout_recorder import (
    RolloutRecorder,
    build_rollout_path,
    resolve_latest_rollout,
)
from pycodex.core.rollout_schema import (
    SCHEMA_VERSION,
    HistoryItem,
    RolloutItem,
    SessionClosed,
    SessionMeta,
    validate_rollout_item,
)
from pycodex.core.session import PromptItem

_KNOWN_TYPES = {
    "session.meta",
    "history.item",
    "turn.completed",
    "compaction.applied",
    "session.closed",
}


@dataclass(frozen=True, slots=True)
class RolloutReplayError(RuntimeError):
    """Replay/import error with a stable machine-readable code."""

    code: Literal["rollout_not_found", "schema_version_mismatch", "replay_failure"]
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ReplayState:
    """Reconstructed session state loaded from a rollout ledger."""

    thread_id: str
    history: list[PromptItem]
    cumulative_usage: dict[str, int]
    turn_count: int
    status: Literal["closed", "incomplete"]
    warnings: list[str]
    session_meta: SessionMeta | None = None
    session_closed: SessionClosed | None = None


def replay_rollout(path: Path, *, expected_major: int = 1) -> ReplayState:
    """Replay a rollout JSONL file into deterministic in-memory session state."""

    if not path.exists():
        raise RolloutReplayError(
            code="rollout_not_found",
            message=f"Rollout file not found: {path}",
        )

    warnings: list[str] = []
    history: list[PromptItem] = []
    thread_id = ""
    session_meta: SessionMeta | None = None
    session_closed: SessionClosed | None = None
    cumulative_usage = {"input_tokens": 0, "output_tokens": 0}
    turn_count = 0

    lines = path.read_text(encoding="utf-8").splitlines()
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            if index == len(lines) - 1:
                warnings.append("ignored truncated final JSONL line")
                break
            raise RolloutReplayError(
                code="replay_failure",
                message=f"Failed to parse rollout line {index + 1}: {exc.msg}",
            ) from exc

        if not isinstance(payload, dict):
            raise RolloutReplayError(
                code="replay_failure",
                message=f"Rollout line {index + 1} is not a JSON object.",
            )

        schema_version = payload.get("schema_version")
        major_version = _schema_major(schema_version)
        if major_version != expected_major:
            raise RolloutReplayError(
                code="schema_version_mismatch",
                message=(
                    f"Unsupported schema_version on line {index + 1}: "
                    f"{schema_version!r} (expected major {expected_major})"
                ),
            )

        payload_type = payload.get("type")
        if not isinstance(payload_type, str):
            raise RolloutReplayError(
                code="replay_failure",
                message=f"Rollout line {index + 1} is missing a valid type.",
            )
        if payload_type not in _KNOWN_TYPES:
            warnings.append(f"ignored unknown rollout record type {payload_type!r}")
            continue

        try:
            item = validate_rollout_item(cast(dict[str, Any], payload))
        except ValidationError as exc:
            raise RolloutReplayError(
                code="replay_failure",
                message=f"Rollout line {index + 1} failed schema validation: {exc}",
            ) from exc

        thread_id = _thread_id_for(item=item, fallback=thread_id)
        _apply_rollout_item(
            item=item,
            history=history,
            cumulative_usage=cumulative_usage,
            state_warnings=warnings,
        )
        if item.type == "turn.completed":
            turn_count += 1
        if isinstance(item, SessionMeta):
            session_meta = item
        elif isinstance(item, SessionClosed):
            session_closed = item

    status: Literal["closed", "incomplete"] = "closed" if session_closed is not None else "incomplete"
    return ReplayState(
        thread_id=thread_id,
        history=history,
        cumulative_usage=cumulative_usage,
        turn_count=turn_count,
        status=status,
        warnings=warnings,
        session_meta=session_meta,
        session_closed=session_closed,
    )


async def import_legacy_session_json(
    legacy_path: Path,
    *,
    thread_id: str | None = None,
    sessions_root: Path | None = None,
) -> Path:
    """Import a legacy ``<id>.json`` session into rollout JSONL format once."""

    if not await asyncio.to_thread(legacy_path.exists):
        raise RolloutReplayError(
            code="rollout_not_found",
            message=f"Legacy session file not found: {legacy_path}",
        )

    try:
        legacy_text = await asyncio.to_thread(legacy_path.read_text, encoding="utf-8")
        payload = json.loads(legacy_text)
    except (OSError, json.JSONDecodeError) as exc:
        raise RolloutReplayError(
            code="replay_failure",
            message=f"Failed to load legacy session file: {legacy_path}",
        ) from exc
    if not isinstance(payload, dict):
        raise RolloutReplayError(
            code="replay_failure",
            message="Legacy session payload must be a JSON object.",
        )

    resolved_thread_id = thread_id or legacy_path.stem
    existing_path = resolve_latest_rollout(resolved_thread_id, root=sessions_root)
    if existing_path is not None:
        existing_state = replay_rollout(existing_path)
        if (
            existing_state.session_meta is not None
            and existing_state.session_meta.import_source == "legacy_json"
        ):
            return existing_path

    rollout_path = build_rollout_path(resolved_thread_id, root=sessions_root)
    recorder = RolloutRecorder(path=rollout_path)

    opened_at = datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    records: list[RolloutItem] = [
        SessionMeta(
            schema_version=SCHEMA_VERSION,
            thread_id=resolved_thread_id,
            profile="legacy",
            model="legacy",
            cwd=str(payload.get("cwd", "")),
            opened_at=opened_at,
            import_source="legacy_json",
        )
    ]

    history_items = payload.get("history")
    if isinstance(history_items, list):
        for item in history_items:
            if isinstance(item, dict):
                records.append(
                    HistoryItem(
                        schema_version=SCHEMA_VERSION,
                        thread_id=resolved_thread_id,
                        item=item,
                    )
                )

    await recorder.record(records)
    await recorder.shutdown()
    return rollout_path


def _apply_rollout_item(
    *,
    item: RolloutItem,
    history: list[PromptItem],
    cumulative_usage: dict[str, int],
    state_warnings: list[str],
) -> None:
    if isinstance(item, HistoryItem):
        history.append(cast(PromptItem, item.item))
        return

    item_type = item.type
    if item_type == "turn.completed":
        turn_completed = cast(Any, item)
        cumulative = turn_completed.usage.cumulative
        cumulative_usage["input_tokens"] = int(cumulative.input_tokens)
        cumulative_usage["output_tokens"] = int(cumulative.output_tokens)
    elif item_type == "compaction.applied":
        # Compaction metadata is replay-safe but does not mutate history directly.
        _ = state_warnings
    elif item_type in {"session.meta", "session.closed"}:
        return


def _thread_id_for(*, item: RolloutItem, fallback: str) -> str:
    if item.thread_id:
        return item.thread_id
    return fallback


def _schema_major(schema_version: object) -> int:
    if not isinstance(schema_version, str):
        raise RolloutReplayError(
            code="replay_failure",
            message=f"Invalid schema_version value: {schema_version!r}",
        )

    major_token = schema_version.split(".", 1)[0]
    if not major_token.isdigit():
        raise RolloutReplayError(
            code="replay_failure",
            message=f"Invalid schema_version value: {schema_version!r}",
        )
    return int(major_token)
