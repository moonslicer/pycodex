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

## Harness Layout
- `tests/agent_harness/fixtures/`: canned inputs and expected outputs/metadata
- `tests/agent_harness/test_*.py`: scenario assertions

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

## CI Integration (Target State)
- Gate merges on harness tests for agent-affecting changes.
- Keep fixture runtime small so checks stay fast.
