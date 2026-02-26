# AI System Map

This document is the architecture map for agent behavior and contracts in this repo.

## Purpose
- Show where AI behavior is defined.
- Keep service boundaries and contracts explicit.
- Point contributors to the correct source of truth before implementation.

## Sources of Truth
- Policy and workflow rules: `AGENTS.md`
- Architecture and responsibilities: `engineering-plan.md`
- Evaluation and regression process: `docs/ai/harness.md`
- Durable decisions and postmortems: `docs/ai/memory.md`

## Contract-First Rules
- Define API and event contracts before implementation details.
- Capture acceptance criteria in the task/PR before coding non-trivial changes.
- Update this map when contract ownership moves.

## Ownership Map (Initial)
- Core agent loop and turn orchestration: `pycodex/core/agent.py` (planned)
- Session and conversation state: `pycodex/core/session.py` (planned)
- Model transport and streaming: `pycodex/core/model_client.py` (planned)
- Tool contracts and dispatch: `pycodex/tools/base.py` and `pycodex/tools/orchestrator.py` (planned)
- Approval and sandbox policies: `pycodex/approval/*.py` (planned)
- Event protocol: `pycodex/protocol/events.py` (planned)

## Update Criteria
Update this file when any of the following change:
- A new service boundary or module ownership is introduced.
- A contract/schema is added or modified.
- A harness surface is added/removed.
