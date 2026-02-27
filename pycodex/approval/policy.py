"""Approval policy types and session-scoped decision cache."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import StrEnum


class ApprovalPolicy(StrEnum):
    """Top-level approval policy mode for mutating tool calls."""

    NEVER = "never"
    ON_FAILURE = "on-failure"
    ON_REQUEST = "on-request"
    UNLESS_TRUSTED = "unless-trusted"


class ReviewDecision(StrEnum):
    """User review decision for a single approval prompt."""

    APPROVED = "approved"
    APPROVED_FOR_SESSION = "approved_for_session"
    DENIED = "denied"
    ABORT = "abort"


@dataclass(slots=True)
class ApprovalStore:
    """In-memory session cache for approval decisions."""

    _cache: dict[str, ReviewDecision] = field(default_factory=dict)
    prompt_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def get(self, key: object) -> ReviewDecision | None:
        """Return the cached decision for a normalized key."""
        return self._cache.get(_normalize_key(key))

    def put(self, key: object, decision: ReviewDecision) -> None:
        """Cache only APPROVED_FOR_SESSION decisions."""
        normalized_key = _normalize_key(key)
        if decision == ReviewDecision.APPROVED_FOR_SESSION:
            self._cache[normalized_key] = decision
            return

        self._cache.pop(normalized_key, None)


def _normalize_key(key: object) -> str:
    return json.dumps(key, sort_keys=True, ensure_ascii=True)
