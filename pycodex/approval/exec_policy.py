"""Deterministic shell command execution classification."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum


class ExecDecision(StrEnum):
    """Decision for whether a shell command should run without prompting."""

    ALLOW = "allow"
    PROMPT = "prompt"
    FORBIDDEN = "forbidden"


DEFAULT_RULES: list[tuple[str, ExecDecision]] = [
    ("rm -rf", ExecDecision.FORBIDDEN),
    ("ls", ExecDecision.ALLOW),
    ("cat", ExecDecision.ALLOW),
    ("echo", ExecDecision.ALLOW),
    ("pwd", ExecDecision.ALLOW),
    ("which", ExecDecision.ALLOW),
    ("env", ExecDecision.ALLOW),
]


def default_heuristics(command: str) -> ExecDecision:
    """Default fallback policy for commands without explicit rules."""

    _ = command
    return ExecDecision.PROMPT


def classify(
    command: str,
    rules: list[tuple[str, ExecDecision]],
    heuristics: Callable[[str], ExecDecision] | None = None,
) -> ExecDecision:
    """Classify a canonical command using ordered prefix rules.

    Matching is token-boundary aware: a prefix matches only when the
    command equals the prefix exactly or the character immediately after
    the prefix is ASCII whitespace.  This prevents bare-word entries like
    ``"ls"`` from matching unrelated commands such as ``lsof``.

    Heuristics, when provided, receive the original *command* string
    (before leading-whitespace stripping) so callers observe a consistent
    contract regardless of internal normalisation.
    """

    stripped_command = command.lstrip()
    for prefix, decision in rules:
        if stripped_command.startswith(prefix):
            rest = stripped_command[len(prefix) :]
            if not rest or rest[0] in (" ", "\t"):
                return decision

    if heuristics is not None:
        return heuristics(command)
    return ExecDecision.PROMPT
