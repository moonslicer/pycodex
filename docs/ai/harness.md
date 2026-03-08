# Agent Harness Guide

This document defines how to evaluate agent behavior changes.

## Goals
- Catch regressions in tool usage, policy enforcement, and response quality.
- Keep behavior checks reproducible and cheap to run locally.
- Make failures actionable with clear fixture ownership.

## Required Command
- `pytest tests/agent_harness/ -v`

Run harness tests when changing:
- Prompts/system instructions
- Tool routing or tool argument schemas
- Approval/sandbox policy behavior
- Agent loop or event protocol behavior

Also run smoke coverage explicitly for agent behavior/policy/orchestration work:

- `pytest tests/agent_harness/test_smoke.py -v`

## Related Test Layers

- Integration coverage: `pytest tests/ -m "integration" -v`
- E2E coverage: `pytest tests/ -m "e2e" -v` (opt-in; requires env vars like `OPENAI_API_KEY`)

Rules:
- Integration tests must be deterministic and avoid live network calls.
- E2E tests may call live services but must skip when required credentials or endpoint availability are missing.
- Harness assertions should validate contract behavior (tool selection, args shape, approval path, event ordering), not stylistic output wording.

## Skills V1 Workflow

When a change touches skill parsing, discovery, catalog rendering, injection, or approval enrichment, run:
- `pytest tests/core/skills -v`
- `pytest tests/core/test_initial_context.py tests/core/test_agent.py tests/tools/test_orchestrator.py -v`
- `pytest tests/agent_harness/test_smoke.py -v`

Skills-specific behavior contracts to validate:
- Invalid `SKILL.md` excludes only that skill; sidecar parse failures are warnings.
- Registry precedence remains deterministic (repo > user > system), and same-scope duplicates stay ambiguous.
- Mention extraction ignores inline/fenced code and injects each resolved skill once per turn.
- Injection ordering stays stable: all `<skill-unavailable>` first, then `<skill>` messages.
- Replay/resume does not re-inject prior `skill_injected` synthetic messages.
- Approval preview `skill_context` is present only for commands under `<skill_root>/scripts`.

## Harness Layout
- `tests/agent_harness/fixtures/`: canned inputs and expected outputs/metadata
- `tests/agent_harness/test_*.py`: scenario assertions

## Current Core Scenarios

Core approval-policy scenarios live in `tests/agent_harness/test_approval_policy_scenarios.py`:
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
