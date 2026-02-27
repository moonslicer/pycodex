# Agent Harness Guide

This document defines how to evaluate agent behavior changes.

## Goals
- Catch regressions in tool usage, policy enforcement, and response quality.
- Keep behavior checks reproducible and cheap to run locally.
- Make failures actionable with clear fixture ownership.

## Required Command
- `pytest tests/agent_harness/ -v`

Run this command when changing:
- Prompts/system instructions
- Tool routing or tool argument schemas
- Approval/sandbox policy behavior
- Agent loop or event protocol behavior

## CLI Integration and E2E
Use marker-based CLI tests for milestone-level validation outside `tests/agent_harness/`.

- Integration marker: `pytest tests/ -m "integration" -v`
- E2E marker: `pytest tests/ -m "e2e" -v`

Rules:
- Integration tests must be deterministic and avoid live network calls.
- E2E tests may call live services but must be opt-in and gate on required env vars.
- OpenAI live E2E requires `OPENAI_API_KEY`; if missing, the test should skip.
- If the OpenAI endpoint is unreachable in the current environment, the live E2E should skip instead of failing unrelated CI jobs.

## Harness Layout
- `tests/agent_harness/fixtures/`: canned inputs and expected outputs/metadata
- `tests/agent_harness/test_*.py`: scenario assertions

## Milestone 2 Coverage Snapshot
- Approval-policy harness coverage lives in:
  - `tests/agent_harness/test_approval_policy_scenarios.py`
- Required scenarios covered:
  - denied decision returns structured denied tool result and turn continues
  - abort decision stops the active turn immediately
  - approved-for-session decision skips the second prompt for the same operation

## Minimum Scenario Shape
Each scenario should define:
- Context/setup inputs
- User task prompt
- Expected tool behavior (which tool(s), key args)
- Expected output constraints (must/must-not)

## Failure Triage
When a harness test fails:
1. Confirm whether the change is intentional.
2. If intentional, update fixture/expectations and explain why in the PR/task summary.
3. If unintentional, fix code/prompt/policy and rerun harness tests.

## CI Integration (Current)
- CI runs:
  - `pytest tests/ --ignore=tests/agent_harness -m "not e2e" -v`
  - `pytest tests/agent_harness/ -v`
  - `pytest tests/ -m "e2e" -v` (PR to `main` only)
- Keep harness fixtures and scenarios deterministic and fast so CI remains actionable.
