from __future__ import annotations

from pycodex.approval.exec_policy import (
    DEFAULT_RULES,
    ExecDecision,
    classify,
    default_heuristics,
)


def test_forbidden_prefix_returns_forbidden() -> None:
    rules = [("rm -rf /", ExecDecision.FORBIDDEN)]

    assert classify("rm -rf /", rules) == ExecDecision.FORBIDDEN


def test_allow_prefix_returns_allow() -> None:
    rules = [("ls", ExecDecision.ALLOW)]

    assert classify("ls -la", rules) == ExecDecision.ALLOW


def test_first_rule_wins() -> None:
    rules = [("rm", ExecDecision.FORBIDDEN), ("rm", ExecDecision.ALLOW)]

    assert classify("rm -rf /tmp/example", rules) == ExecDecision.FORBIDDEN


def test_no_match_calls_heuristics() -> None:
    def heuristics(_: str) -> ExecDecision:
        return ExecDecision.FORBIDDEN

    assert classify("python -V", [], heuristics) == ExecDecision.FORBIDDEN


def test_no_match_no_heuristics_returns_prompt() -> None:
    assert classify("python -V", []) == ExecDecision.PROMPT


def test_heuristics_not_called_when_rule_matches() -> None:
    called = False

    def heuristics(_: str) -> ExecDecision:
        nonlocal called
        called = True
        return ExecDecision.FORBIDDEN

    result = classify("ls -la", [("ls", ExecDecision.ALLOW)], heuristics)

    assert result == ExecDecision.ALLOW
    assert called is False


def test_default_rules_exportable() -> None:
    assert DEFAULT_RULES
    for rule in DEFAULT_RULES:
        assert isinstance(rule, tuple)
        assert len(rule) == 2
        prefix, decision = rule
        assert isinstance(prefix, str)
        assert isinstance(decision, ExecDecision)


def test_default_heuristics_returns_prompt() -> None:
    assert default_heuristics("anything") == ExecDecision.PROMPT


def test_default_rules_forbid_dangerous_commands() -> None:
    # Broad "rm -rf" rule catches all targets, not just / and ~
    assert classify("rm -rf /", DEFAULT_RULES, default_heuristics) == ExecDecision.FORBIDDEN
    assert classify("rm -rf ~", DEFAULT_RULES, default_heuristics) == ExecDecision.FORBIDDEN
    assert classify("rm -rf /tmp/foo", DEFAULT_RULES, default_heuristics) == ExecDecision.FORBIDDEN


def test_default_rules_allow_safe_commands() -> None:
    assert classify("ls -la", DEFAULT_RULES, default_heuristics) == ExecDecision.ALLOW


def test_classify_is_pure_no_side_effects() -> None:
    rules = [("ls", ExecDecision.ALLOW)]

    first = classify("ls -la", rules, default_heuristics)
    second = classify("ls -la", rules, default_heuristics)

    assert first == second == ExecDecision.ALLOW


# P1 regression: bare-word prefixes must not overmatch adjacent command names
def test_default_rules_do_not_overmatch_lsof() -> None:
    assert classify("lsof", DEFAULT_RULES, default_heuristics) == ExecDecision.PROMPT


def test_default_rules_do_not_overmatch_catapult() -> None:
    assert classify("catapult", DEFAULT_RULES, default_heuristics) == ExecDecision.PROMPT


def test_default_rules_do_not_overmatch_envsubst() -> None:
    assert classify("envsubst", DEFAULT_RULES, default_heuristics) == ExecDecision.PROMPT


# P2 regression: heuristics must receive the original command, not stripped_command
def test_heuristics_receives_original_command() -> None:
    received: list[str] = []

    def capturing(cmd: str) -> ExecDecision:
        received.append(cmd)
        return ExecDecision.PROMPT

    original = "  python -V"
    classify(original, [], capturing)

    assert received == [original]
