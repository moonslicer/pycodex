from __future__ import annotations

import asyncio

from pycodex.approval.policy import ApprovalStore, ReviewDecision


def test_approval_store_get_returns_none_when_key_missing() -> None:
    store = ApprovalStore()

    assert store.get({"tool": "shell", "cmd": "ls"}) is None


def test_approval_store_normalizes_key_order() -> None:
    store = ApprovalStore()
    key1 = {"tool": "shell", "cmd": "ls"}
    key2 = {"cmd": "ls", "tool": "shell"}

    store.put(key1, ReviewDecision.APPROVED_FOR_SESSION)

    assert store.get(key2) == ReviewDecision.APPROVED_FOR_SESSION


def test_approval_store_caches_approved_for_session_only() -> None:
    store = ApprovalStore()
    key = {"tool": "shell", "cmd": "ls"}

    store.put(key, ReviewDecision.APPROVED_FOR_SESSION)

    assert store.get(key) == ReviewDecision.APPROVED_FOR_SESSION


def test_approval_store_does_not_cache_approved() -> None:
    store = ApprovalStore()
    key = {"tool": "shell", "cmd": "ls"}

    store.put(key, ReviewDecision.APPROVED)

    assert store.get(key) is None


def test_approval_store_non_session_decisions_clear_existing_cache() -> None:
    store = ApprovalStore()
    key = {"tool": "shell", "cmd": "ls"}
    store.put(key, ReviewDecision.APPROVED_FOR_SESSION)

    store.put(key, ReviewDecision.DENIED)
    assert store.get(key) is None

    store.put(key, ReviewDecision.APPROVED_FOR_SESSION)
    store.put(key, ReviewDecision.ABORT)
    assert store.get(key) is None


def test_approval_store_exposes_prompt_lock() -> None:
    store = ApprovalStore()

    assert isinstance(store.prompt_lock, asyncio.Lock)
