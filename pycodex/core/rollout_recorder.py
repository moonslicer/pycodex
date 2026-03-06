"""Async JSONL rollout recorder and path helpers for session persistence."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from pycodex.core.rollout_schema import RolloutItem

_THREAD_ID_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def default_sessions_root() -> Path:
    """Return the active rollout root directory."""

    return Path.home() / ".pycodex" / "sessions"


def default_archived_sessions_root() -> Path:
    """Return the archived rollout root directory."""

    return Path.home() / ".pycodex" / "archived_sessions"


def build_rollout_path(
    thread_id: str,
    *,
    now: datetime | None = None,
    root: Path | None = None,
) -> Path:
    """Build a rollout path using a sortable flat filename layout."""

    timestamp = now or datetime.now(tz=UTC)
    date_part = timestamp.strftime("%Y%m%d")
    time_part = timestamp.strftime("%H%M%S%f")
    safe_thread_id = sanitize_thread_id(thread_id)
    filename = f"rollout-{date_part}-{time_part}-{safe_thread_id}.jsonl"
    return (root or default_sessions_root()) / filename


def resolve_latest_rollout(
    thread_id: str,
    *,
    root: Path | None = None,
) -> Path | None:
    """Resolve the newest rollout path for ``thread_id`` by filename sort."""

    base = root or default_sessions_root()
    safe_thread_id = sanitize_thread_id(thread_id)
    candidates = sorted(base.glob(f"rollout-*-{safe_thread_id}.jsonl"), key=lambda path: path.name)
    if not candidates:
        return None
    return candidates[-1]


def sanitize_thread_id(thread_id: str) -> str:
    """Normalize thread IDs so they are safe in rollout filenames."""

    normalized = _THREAD_ID_SANITIZE_RE.sub("_", thread_id.strip()).strip("_")
    if normalized:
        return normalized
    return "thread"


@dataclass(frozen=True, slots=True)
class _WriteBatch:
    items: tuple[RolloutItem, ...]


@dataclass(frozen=True, slots=True)
class _FlushRequest:
    future: asyncio.Future[None]


@dataclass(frozen=True, slots=True)
class _ShutdownRequest:
    future: asyncio.Future[None]


_QueueItem = _WriteBatch | _FlushRequest | _ShutdownRequest


@dataclass(slots=True)
class RolloutRecorder:
    """Queue-backed single-writer JSONL recorder for one session."""

    path: Path
    flush_timeout: float = 30.0
    _queue: asyncio.Queue[_QueueItem] = field(init=False, default_factory=asyncio.Queue)
    _worker_task: asyncio.Task[None] | None = None
    _closed: bool = False
    _worker_error: Exception | None = None

    async def record(self, items: Sequence[RolloutItem]) -> None:
        """Queue rollout records for append-only writing."""

        if self._closed:
            raise RuntimeError("Recorder is already closed.")
        if self._worker_error is not None:
            raise RuntimeError("Recorder worker failed.") from self._worker_error
        if len(items) == 0:
            return

        self._ensure_worker()
        await self._queue.put(_WriteBatch(items=tuple(items)))

    async def flush(self) -> None:
        """Flush queued records to durable storage."""

        if self._closed:
            return
        if self._worker_error is not None:
            raise RuntimeError("Recorder worker failed.") from self._worker_error

        self._ensure_worker()
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        await self._queue.put(_FlushRequest(future=future))
        try:
            await asyncio.wait_for(asyncio.shield(future), timeout=self.flush_timeout)
        except TimeoutError:
            self._closed = True
            if self._worker_task is not None:
                self._worker_task.cancel()
            raise RuntimeError(
                f"Rollout flush timed out after {self.flush_timeout}s — "
                "possible disk stall or worker deadlock."
            ) from None

    async def shutdown(self) -> None:
        """Flush all pending records and stop the writer task."""

        if self._closed:
            return
        if self._worker_error is not None:
            raise RuntimeError("Recorder worker failed.") from self._worker_error

        self._ensure_worker()
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        await self._queue.put(_ShutdownRequest(future=future))
        try:
            await asyncio.wait_for(asyncio.shield(future), timeout=self.flush_timeout)
        except TimeoutError:
            self._closed = True
            if self._worker_task is not None:
                self._worker_task.cancel()
            raise RuntimeError(
                f"Rollout shutdown timed out after {self.flush_timeout}s — "
                "possible disk stall or worker deadlock."
            ) from None
        task = self._worker_task
        if task is not None:
            await task
        self._closed = True

    def _ensure_worker(self) -> None:
        if self._worker_task is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._worker_task = asyncio.create_task(self._run_worker())

    async def _run_worker(self) -> None:
        try:
            _guard_newline_boundary(self.path)
            with self.path.open("a", encoding="utf-8") as handle:
                while True:
                    request = await self._queue.get()
                    try:
                        if isinstance(request, _WriteBatch):
                            self._write_batch(handle, request.items)
                        elif isinstance(request, _FlushRequest):
                            _flush_handle(handle)
                            request.future.set_result(None)
                        else:
                            _flush_handle(handle)
                            request.future.set_result(None)
                            return
                    finally:
                        self._queue.task_done()
        except Exception as exc:  # pragma: no cover - defensive boundary
            # Set _closed before _fail_pending_waiters so any concurrent record()/
            # flush()/shutdown() calls that pass the _worker_error guard will hit
            # the _closed guard instead and not enqueue new items after the drain.
            self._closed = True
            self._worker_error = exc
            await self._fail_pending_waiters(exc)
            raise

    async def _fail_pending_waiters(self, exc: Exception) -> None:
        while not self._queue.empty():
            request = await self._queue.get()
            try:
                if isinstance(request, _WriteBatch):
                    continue
                if not request.future.done():
                    request.future.set_exception(exc)
            finally:
                self._queue.task_done()

    @staticmethod
    def _write_batch(handle: TextIO, items: Sequence[RolloutItem]) -> None:
        for item in items:
            handle.write(item.model_dump_json())
            handle.write("\n")


def _guard_newline_boundary(path: Path) -> None:
    """Ensure EOF has a safe line boundary before appending JSONL records.

    If the last line is a complete JSON object but just missing ``\\n``, append
    the newline to preserve that record. If the tail is partial/invalid JSON,
    truncate back to the last newline boundary so future appends remain replayable.
    """
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return
    if size == 0:
        return

    with path.open("rb") as f:
        f.seek(-1, 2)
        if f.read(1) == b"\n":
            return

    boundary = _last_newline_boundary(path=path, size=size)
    with path.open("rb") as f:
        f.seek(boundary)
        tail = f.read()

    if _is_complete_json_object_line(tail):
        with path.open("ab") as f:
            f.write(b"\n")
        return

    with path.open("r+b") as f:
        f.truncate(boundary)


def _last_newline_boundary(*, path: Path, size: int) -> int:
    chunk_size = 4096
    pos = size
    with path.open("rb") as f:
        while pos > 0:
            read_size = min(chunk_size, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            newline_offset = chunk.rfind(b"\n")
            if newline_offset != -1:
                return pos + newline_offset + 1
    return 0


def _is_complete_json_object_line(raw_tail: bytes) -> bool:
    try:
        decoded = raw_tail.decode("utf-8").strip()
    except UnicodeDecodeError:
        return False
    if not decoded:
        return False
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict)


def _flush_handle(handle: TextIO) -> None:
    handle.flush()
    os.fsync(handle.fileno())
