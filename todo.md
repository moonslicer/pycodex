# Skills V1 TODO

Source: `skills-plan.md` (last updated 2026-03-07)

## Release Goal
Ship Skills v1 with explicit invocation, lazy loading, deterministic behavior, and no regressions to existing agent/tool orchestration contracts.

## Release Non-Goals
1. No model-primary `Skill` tool path.
2. No forked sub-agent execution.
3. No marketplace install/update flow.
4. No file watcher or dynamic path activation.
5. No protocol event expansion unless strictly required.

## Task Structure Rule
Each task below is independently scoped and verifiable. A task is complete only when its verification commands pass and its acceptance checks are met.

---

## T1. Skills Domain Models + Parser Contract
- [ ] Status: Pending
- Goal: Define strict v1 skill metadata types and parse `SKILL.md` frontmatter deterministically.
- Non-goals: Discovery, runtime injection, approval integration.
- Scope:
  - `pycodex/core/skills/models.py` (new)
  - `pycodex/core/skills/parser.py` (new)
  - `tests/core/skills/test_parser.py` (new)
- Deliverables:
  1. `SkillMetadata`, `SkillLoadOutcome`, dependency/policy types.
  2. Required frontmatter validation: `name`, `description`.
  3. Optional sidecar parse shape with fail-open warnings.
- Verification:
  - `.venv/bin/pytest tests/core/skills/test_parser.py -v`
- Acceptance checks:
  1. Malformed `SKILL.md` excludes only that skill.
  2. Optional sidecar parse errors do not crash loading.

## T2. Discovery Pipeline + Deterministic Registry
- [ ] Status: Pending
- Goal: Discover skills across repo/user/system roots with canonical dedupe and deterministic precedence.
- Non-goals: Prompt rendering, turn-time injection.
- Scope:
  - `pycodex/core/skills/discovery.py` (new)
  - `pycodex/core/skills/manager.py` (new)
  - `tests/core/skills/test_discovery.py` (new)
  - `tests/core/skills/test_manager.py` (new)
- Deliverables:
  1. Root collection in precedence order (repo > user > system).
  2. Canonical path dedupe and bounded traversal.
  3. Deterministic conflict handling (cross-scope precedence, same-scope ambiguity).
  4. Cache keyed by cwd/config fingerprint.
- Verification:
  - `.venv/bin/pytest tests/core/skills/test_discovery.py tests/core/skills/test_manager.py -v`
- Acceptance checks:
  1. Same name across scopes resolves by precedence.
  2. Same name within same scope is marked ambiguous.

## T3. Mention Extraction + Resolution Engine
- [ ] Status: Pending
- Goal: Resolve explicit skill mentions from user text and path-linked references deterministically.
- Non-goals: Session mutation and model sampling changes.
- Scope:
  - `pycodex/core/skills/resolver.py` (new)
  - `tests/core/skills/test_resolver.py` (new)
- Deliverables:
  1. Mention parsing rules for `$name` and path-linked form.
  2. Exclusion of code-fence and inline-code matches.
  3. Ordered deduped resolution result (path-linked first, then plain names).
- Verification:
  - `.venv/bin/pytest tests/core/skills/test_resolver.py -v`
- Acceptance checks:
  1. Duplicate mentions inject only once.
  2. Ambiguous names return deterministic unresolved status.

## T4. Initial Context Skills Catalog Rendering
- [ ] Status: Pending
- Goal: Append compact `## Skills` metadata section to initial context when enabled skills exist.
- Non-goals: Full skill-body injection and dependency prompts.
- Scope:
  - `pycodex/core/skills/render.py` (new)
  - `pycodex/core/initial_context.py` (update)
  - `tests/core/skills/test_render.py` (new)
  - `tests/core/test_initial_context.py` (update)
- Deliverables:
  1. Catalog format contract implemented.
  2. 2000-character truncation behavior with `(and N more...)` suffix.
  3. Section omitted entirely for zero enabled skills.
- Verification:
  - `.venv/bin/pytest tests/core/skills/test_render.py tests/core/test_initial_context.py -v`
- Acceptance checks:
  1. Bullet order matches registry order.
  2. No path/arguments/when-to-use leakage in listing.

## T5. Turn-Time Skill Injection (Explicit Path)
- [ ] Status: Pending
- Goal: Inject selected skill bodies as synthetic user messages before model sampling.
- Non-goals: New tools, tool routing changes, parallel dispatch changes.
- Scope:
  - `pycodex/core/skills/injector.py` (new)
  - `pycodex/core/agent.py` (update)
  - `tests/core/test_agent.py` (update)
  - `tests/agent_harness/` targeted scenarios (new/updated)
- Deliverables:
  1. `<skill>` payload injection in mention-appearance order.
  2. Injection metadata marker (`skill_injected: true`) persisted in history envelope.
  3. Missing skill file handled via `<skill-unavailable>` message.
- Verification:
  - `.venv/bin/pytest tests/core/test_agent.py -v`
  - `.venv/bin/pytest tests/agent_harness/test_smoke.py -v`
- Acceptance checks:
  1. Existing tool list and sampling pipeline remain unchanged.
  2. Injected items survive replay as normal history entries.

## T6. Dependency Gate + Unavailable Messaging
- [ ] Status: Pending
- Goal: Enforce env-var dependencies for selected skills and fail open with deterministic model-visible warnings.
- Non-goals: Interactive dependency prompts, MCP install/login flow.
- Scope:
  - `pycodex/core/skills/resolver.py` (update)
  - `tests/core/skills/` dependency-focused tests (new/updated)
- Deliverables:
  1. Env-var dependency checks (`env_var` type).
  2. `<skill-unavailable>` messages with exact reason for missing deps.
  3. Required ordering: all unavailable messages before any `<skill>` messages.
- Verification:
  - `.venv/bin/pytest tests/core/skills -v`
- Acceptance checks:
  1. Dependency failure never crashes turn.
  2. Dependency failure reason is deterministic and specific.

## T7. Replay/Resume Idempotence for Skill Injection
- [ ] Status: Pending
- Goal: Prevent duplicate skill injection after session replay/resume.
- Non-goals: Rollout schema changes, session format migrations.
- Scope:
  - `pycodex/core/skills/injector.py` (update)
  - `pycodex/core/rollout_replay.py` or relevant replay path (update if needed)
  - `tests/agent_harness/` replay scenarios (new/updated)
- Deliverables:
  1. Turn-position check for existing `skill_injected: true` entries.
  2. Skip behavior with deterministic replay-skip logging.
- Verification:
  - `.venv/bin/pytest tests/agent_harness -k "skill and replay" -v`
- Acceptance checks:
  1. Resume does not re-inject prior `<skill>` messages.
  2. Resume does not re-emit prior `<skill-unavailable>` messages.

## T8. Approval Preview Context for Skill Scripts
- [ ] Status: Pending
- Goal: Add skill-aware context to approval preview when commands execute under `skill_root/scripts`.
- Non-goals: New approval policies, changed approval key semantics.
- Scope:
  - `pycodex/tools/orchestrator.py` or approval preview helper path (update)
  - `tests/tools/test_orchestrator.py` (update)
- Deliverables:
  1. Skill script detection by canonical path.
  2. Approval preview enrichment with skill identity metadata.
- Verification:
  - `.venv/bin/pytest tests/tools/test_orchestrator.py -v`
- Acceptance checks:
  1. Existing approval behavior remains intact.
  2. Skill context appears only for skill-script paths.

## T9. Skills Observability + Safety Hardening
- [ ] Status: Pending
- Goal: Emit structured skill lifecycle logs and enforce path/safety constraints.
- Non-goals: Analytics dashboards, protocol-level skills events.
- Scope:
  - `pycodex/core/skills/*` (update)
  - `tests/core/skills/` log/safety tests (new/updated)
- Deliverables:
  1. `pycodex.skills` logger events (`loaded`, `load_error`, `load_warning`, `injected`, `unavailable`, `replay_skip`).
  2. Canonical path validation and traversal rejection outside allowed roots.
  3. Log redaction guarantee for secret-adjacent values.
- Verification:
  - `.venv/bin/pytest tests/core/skills -v`
- Acceptance checks:
  1. No skill body or env-var values appear in logs.
  2. Invalid paths are rejected deterministically.

## T10. Docs + Final Integration Gates
- [ ] Status: Pending
- Goal: Finalize architecture/test docs and pass required quality gates for the delivered scope.
- Non-goals: V2/V3 roadmap implementation.
- Scope:
  - `docs/ai/system-map.md` (update)
  - `docs/ai/harness.md` (update)
  - `docs/ai/memory.md` (optional update for durable decisions)
- Deliverables:
  1. Skills architecture and test workflow documentation.
  2. Deferred-item tracking for v2/v3.
  3. Final verification report.
- Verification:
  - `.venv/bin/ruff check . --fix`
  - `.venv/bin/ruff format .`
  - `.venv/bin/mypy --strict pycodex/`
  - `.venv/bin/pytest tests/core/skills -v`
  - `.venv/bin/pytest tests/core/test_initial_context.py tests/core/test_agent.py tests/tools/test_orchestrator.py -v`
  - `.venv/bin/pytest tests/agent_harness/test_smoke.py -v`
- Acceptance checks:
  1. No regressions in existing agent/orchestrator contracts.
  2. Skills v1 acceptance criteria from `skills-plan.md` are satisfied.

---

## Suggested Execution Order
1. T1 -> T2 -> T3 -> T4
2. T5 -> T6 -> T7
3. T8 -> T9 -> T10

## Per-Task Completion Template
Use this when closing a task:
1. Files changed.
2. Behavior/contract changes.
3. Verification commands + pass/fail output summary.
4. Residual risks or deferred follow-ups.
