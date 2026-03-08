# PyCodex Skills Plan

Last updated: 2026-03-07 (rev 2)

## Purpose

Define a skills system for pycodex that balances simplification and feature completeness.
This document is implementation-oriented and intended to let another engineer or agent build the feature end-to-end without re-deriving architecture decisions.

## Primary Outcomes

1. Add skills without breaking current pycodex runtime contracts in `engineering-plan.md`.
2. Keep v1 simple: explicit invocation, lazy loading, deterministic behavior.
3. Preserve a clear path to v2/v3 completeness (model-invoked skills, dynamic activation, richer dependency flows).

## Goals

1. Support markdown-defined skills (`SKILL.md`) with deterministic metadata parsing.
2. Discover skills from layered roots with canonical dedupe and stable precedence.
3. Expose compact skill metadata to the model at session startup.
4. Inject full skill instructions only for explicitly selected skills.
5. Keep tool routing and approval orchestration unchanged in v1.
6. Make failure behavior deterministic and fail-open where safe.
7. Provide a high-signal test matrix that validates behavior contracts.

## Non-Goals (v1)

1. Do not make a new model-visible `Skill` tool the primary invocation path.
2. Do not implement forked sub-agent execution for skills.
3. Do not implement plugin marketplace install/update mechanics.
4. Do not add filesystem watchers or dynamic path activation in v1.
5. Do not change existing protocol events unless strictly needed.

## Existing Architecture Constraints

These constraints come from the current pycodex architecture and must remain true in v1:

1. `Session` is the only owner of prompt history mutation (`pycodex/core/session.py`).
2. Agent loop remains sequential for tool dispatch (`pycodex/core/agent.py`, `pycodex/core/AGENTS.md`).
3. `ToolAborted` remains terminal for the active turn.
4. Tool approval and sandboxing remain centralized in `pycodex/tools/orchestrator.py`.
5. `profile.instructions` is stable instruction policy; initial-context system messages carry dynamic environment/project context.
6. Rollout replay and resume must remain deterministic.

## Design Summary

V1 uses a Codex-style progressive disclosure model aligned with pycodex:

1. Stage A (metadata): append a compact `## Skills` inventory to initial context system content.
2. Stage B (full body): when user explicitly invokes a skill, inject that skill as a synthetic user message before model sampling.
3. Keep existing tools (`shell`, `write_file`, etc.) as the only executable path.

This gives low implementation risk, good token efficiency, and strong extensibility.

## Architecture

```mermaid
flowchart LR
  A["Skill roots"] --> B["Discovery + parser"]
  B --> C["Skills registry cache (by cwd)"]
  C --> D["Initial context renderer: compact Skills list"]
  C --> E["Turn skill resolver: explicit mentions"]
  E --> F["Dependency gate"]
  F --> G["Skill injector (<skill> user message)"]
  D --> H["Session prompt history"]
  G --> H
  H --> I["ModelClient stream(instructions + input + tools)"]
  I --> J["Existing tool router + orchestrator"]
```

## Core Design Decisions

### Decision 1: Explicit mention invocation is primary

- Decision: skills are invoked via explicit user mention (`$name` or path-linked mention), not a primary `Skill` tool call.
- Why: avoids expanding tool contracts and agent loop control flow in v1.
- Tradeoff: model has less autonomous skill invocation power.

### Decision 2: Two-channel prompt strategy

- Decision: put stable skills policy in `profile.instructions`; put dynamic catalog in initial-context system message.
- Why: stable policy belongs in `instructions`; inventory is environment-dependent and should be persisted/replayed in history.
- Tradeoff: duplicate conceptual context split across two channels.

### Decision 3: Lazy full-body loading only

- Decision: do not preload all `SKILL.md` bodies globally.
- Why: token efficiency and lower prompt pollution.
- Tradeoff: requires resolver/injector step per turn.

### Decision 4: Fail-open optional metadata

- Decision: malformed optional sidecar metadata warns and continues; malformed `SKILL.md` skips that skill.
- Why: keeps runtime resilient to partially broken skill trees.
- Tradeoff: feature loss for broken skills rather than hard failure.

### Decision 5: No watcher in v1

- Decision: cache by cwd with explicit reload semantics; no file watcher in v1.
- Why: simpler state model and fewer race conditions.
- Tradeoff: skill edits are visible on next cache reload boundary.

## Skill Definition

### Required file layout

Each skill is a directory containing `SKILL.md`.

Example:

```text
.agents/skills/db-migrate/
  SKILL.md
  agents/openai.yaml            # optional
  scripts/generate.sh           # optional
  assets/icon.svg               # optional
```

### `SKILL.md` contract (v1)

Required frontmatter fields:

1. `name: str`
2. `description: str`

Optional frontmatter fields (accepted, not all enforced in v1):

1. `metadata.short-description`
2. `when-to-use`
3. `arguments`

Body:

1. Treated as the full skill instruction payload.
2. Injected verbatim (with minimal framing) when selected.

Example:

```md
---
name: db-migrate
description: Generate SQL migrations with rollback and verification.
metadata:
  short-description: Safe migration workflow
---
When invoked:
1. Inspect schema and constraints.
2. Propose up/down SQL.
3. Add a verification query.
```

### Optional sidecar metadata (`agents/openai.yaml`)

v1-parsed fields:

1. `dependencies` (env var declarations first-class in v1)
2. `policy.allow_implicit_invocation`
3. `interface` display hints
4. `permissions` or profile hints for later phases

Validation posture:

1. Parse and validate shape.
2. On error: emit warning, keep skill if `SKILL.md` is valid.

## Registry and Discovery

### Registry responsibilities

1. Provide enabled skill set for a cwd.
2. Provide deterministic lookup by name and by absolute path.
3. Carry load warnings and disabled-path diagnostics.
4. Provide script-path index for implicit invocation tagging.

### Suggested types

```python
@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    short_description: str | None
    path_to_skill_md: Path
    skill_root: Path
    scope: Literal["repo", "user", "system"]
    dependencies: SkillDependencies | None
    allow_implicit_invocation: bool

@dataclass(frozen=True)
class SkillLoadOutcome:
    skills: tuple[SkillMetadata, ...]
    errors: tuple[str, ...]
    disabled_paths: tuple[Path, ...]
```

### Root precedence (v1)

V1 defines three scopes: `repo`, `user`, `system`. Admin scope is not supported in v1.

Discovery order (highest to lowest precedence):

1. Repo scope: `.agents/skills` directories found walking from repo root to cwd (ancestor chain).
2. Repo scope: project-configured skill dirs from `pycodex.toml` (if configured); treated as repo scope.
3. User scope: `$HOME/.agents/skills` (or user config override).
4. System scope: `$PYCODEX_HOME/skills/.system` (embedded or installed system skills).

### Discovery algorithm

1. Collect roots in precedence order.
2. Canonicalize (`Path.resolve`) and dedupe roots.
3. Bounded traversal (depth and directory-count limits).
4. Accept directories containing `SKILL.md`.
5. Parse `SKILL.md`, then optional sidecar metadata.
6. Canonicalize skill path and dedupe conflicts deterministically.
7. Build indexes:
- by name
- by path
- by `scripts/` directory

Conflict handling:

1. If same canonical skill path appears twice, keep first and record warning.
2. If same name appears across different scopes, resolve by scope precedence (repo > user > system): keep the highest-precedence skill and record a debug log. Do not mark as ambiguous.
3. If same name appears within the same scope (true duplicate), keep first encountered and mark name as ambiguous so plain-name mentions are rejected with a deterministic warning.

## Invocation Model

### Invocation trigger sources

v1 explicit triggers:

1. `$skill-name` mention in user text.
2. Path-linked form (for example, `[$skill-name](/abs/path/to/SKILL.md)`).

Future optional trigger:

1. Structured input item (if TUI/client sends explicit skill selection object).

### Mention extraction rules

Apply to raw user text before registry lookup:

1. Pattern: `\$([a-zA-Z0-9][a-zA-Z0-9_-]*)` — dollar sign followed by an identifier starting with an alphanumeric character.
2. Name terminates at the first character that is not `[a-zA-Z0-9_-]` (space, punctuation, newline, end of string).
3. Path-linked form: `\[([^\]]+)\]\((/[^)]+)\)` — extract name from link text, path from link target.
4. Skip mentions inside fenced code blocks (triple backtick or triple tilde) and inline code spans (single backtick).
5. Duplicate mentions of the same name in one user message inject the skill exactly once.
6. Extraction produces an ordered list: path-linked mentions first (left-to-right), then plain-name mentions (left-to-right), deduped by resolved skill path.

### Turn-time invocation sequence

1. Receive user input.
2. Extract mention candidates from user text using the extraction rules above.
3. Resolve mentions against current registry with ambiguity rules:
   - Path-linked match wins on exact canonical path regardless of name.
   - Plain name resolves when exactly one enabled skill matches (cross-scope already resolved by precedence at registry build time; only same-scope true duplicates remain ambiguous).
   - Ambiguous plain names are skipped with a deterministic warning message injected before the model sample (see dependency failure format below).
4. Resolve dependencies for each resolved skill.
5. Inject selected skills as synthetic user messages in this order:
   - First, any `<skill-unavailable>` messages for skipped skills (ambiguity or dependency failure).
   - Then, one `<skill>` message per successfully resolved skill, in mention-appearance order (left-to-right in user text).

```xml
<skill>
<name>db-migrate</name>
<path>/abs/path/to/SKILL.md</path>
...full SKILL.md contents...
</skill>
```

6. Each injected message is tagged with `role: "user"` and carries a `skill_injected: true` marker in session metadata so the replayer can detect already-injected turns (see Replay and Resume).
7. Run normal `model_client.stream(...)` with unchanged tools list.

### Placement of stable policy vs dynamic catalog

1. Stable skills policy text goes into `profile.instructions` (or profile override).
2. Dynamic `## Skills` catalog goes into initial-context system message so it is session-scoped, replayable, and cwd-specific.

### `## Skills` section format contract

If zero enabled skills exist, omit the `## Skills` section entirely — emit no heading, no placeholder text.

If one or more enabled skills exist, append the following block to the initial-context system message:

```text
## Skills

The following skills are available. Mention `$skill-name` to invoke a skill.
Use only skills listed here. Do not guess skill names.

- <name>: <description>[ — <short-description>]
- <name>: <description>
...
```

Formatting rules:

1. One bullet per enabled skill, in registry order (precedence order, then discovery order within a scope).
2. Include `short-description` in parenthetical only if present; omit otherwise.
3. Truncation budget: if total section length exceeds 2000 characters, truncate the list at the last complete bullet that fits and append `(and N more — use $skill-name by exact name to invoke)`.
4. Do not include `path`, `arguments`, or `when-to-use` in this listing — metadata only.
5. `when-to-use` is reserved for v2 extended listing format.

## Dependencies and Approval Integration

### Dependency gate (v1)

Supported first-class dependency type:

1. `env_var` requirements.

Behavior:

1. If required env var exists in process env, mark satisfied.
2. If missing, do NOT silently skip. Inject a `<skill-unavailable>` message before the model sample so the model can inform the user of the exact reason:

```xml
<skill-unavailable>
<name>db-migrate</name>
<reason>missing required env var: DATABASE_URL</reason>
</skill-unavailable>
```

3. Log the failure at `WARNING` level (see Observability).
4. Optional interactive prompting for missing values is deferred to v2.

Deferred to v2:

1. MCP server install/login orchestration.

### Approval integration

1. Keep all execution within existing tools/orchestrator pipeline.
2. For commands under `skill_root/scripts`, enrich approval preview with skill context.
3. Preserve existing approval key semantics and session-scoped approvals.

## Error Handling Contracts

1. Skill load errors are non-fatal and aggregated.
2. Malformed `SKILL.md` excludes only that skill.
3. Missing selected skill file at injection time injects `<skill-unavailable>` with `reason: file not found` and continues without that skill.
4. Invocation ambiguity never silently chooses a random skill; injects `<skill-unavailable>` with `reason: ambiguous name`.
5. Dependency failure never crashes a turn; injects `<skill-unavailable>` with `reason: missing required env var: VAR_NAME`.
6. All `<skill-unavailable>` messages are injected before any `<skill>` messages in the same turn so the model reads failures before instructions.

## Security and Safety

1. Canonicalize all paths before registration/invocation.
2. Reject path traversal outside allowed roots for discovered skills.
3. Redact sensitive values in any skill-related previews/logs.
4. Never execute skill files directly; only inject instructions or run explicit shell tools under existing approvals.

## Replay and Resume

Injected skill messages are persisted as normal session history items. On resume, the replayer must not re-inject skills that were already injected in the replayed turn. The contract:

1. Each synthetic message (both `<skill>` and `<skill-unavailable>`) carries a `skill_injected: true` field in its session metadata envelope (not in the message content).
2. The injector checks, for each resolved skill path, whether a `skill_injected: true` message for that path already exists in history at the same turn position.
3. If found, skip injection for that skill. Do not inject again.
4. If not found (new session or first occurrence), inject normally.

This prevents double-injection on resume while keeping skill bodies in the replayed history for model context continuity.

## Observability

Emit structured log events for all skill lifecycle actions. Use Python `logging` with a `pycodex.skills` logger hierarchy. All events include `name` and `scope` where applicable.

| Event | Level | Fields |
|---|---|---|
| `skill.loaded` | `DEBUG` | `name`, `scope`, `path` |
| `skill.load_error` | `WARNING` | `path`, `reason` |
| `skill.load_warning` | `WARNING` | `path`, `reason` (sidecar parse failure) |
| `skill.dedup_skipped` | `DEBUG` | `name`, `scope`, `kept_path`, `skipped_path` |
| `skill.injected` | `INFO` | `name`, `scope`, `path` |
| `skill.unavailable` | `WARNING` | `name`, `reason` |
| `skill.replay_skip` | `DEBUG` | `name`, `path` (skipped on resume) |

No skill body content, env var values, or secret-adjacent fields are included in any log event.

## Implementation Plan

The implementation is split into focused phases to keep behavior changes reviewable.

### Phase 1: Models and parser

Files:

1. Add `pycodex/core/skills/models.py`
2. Add `pycodex/core/skills/parser.py`
3. Add tests under `tests/core/skills/test_parser.py`

Deliverables:

1. `SKILL.md` frontmatter parser with required field validation.
2. Optional sidecar parser with fail-open warnings.

Verification:

1. `pytest tests/core/skills/test_parser.py -v`

### Phase 2: Discovery and registry

Files:

1. Add `pycodex/core/skills/discovery.py`
2. Add `pycodex/core/skills/manager.py`
3. Add `pycodex/core/skills/resolver.py`
4. Add tests under `tests/core/skills/test_discovery.py`, `test_manager.py`, `test_resolver.py`

Deliverables:

1. Root collection, canonical dedupe, bounded traversal.
2. Registry cache keyed by cwd and config fingerprint.
3. Deterministic name/path resolution with ambiguity handling.

Verification:

1. `pytest tests/core/skills/test_discovery.py tests/core/skills/test_manager.py tests/core/skills/test_resolver.py -v`

### Phase 3: Initial context skills catalog

Files:

1. Update `pycodex/core/initial_context.py`
2. Add `pycodex/core/skills/render.py`
3. Add tests under `tests/core/test_initial_context.py` and `tests/core/skills/test_render.py`

Deliverables:

1. Compact `## Skills` metadata section appended to project instructions message.
2. Deterministic formatting and truncation budget.

Verification:

1. `pytest tests/core/test_initial_context.py tests/core/skills/test_render.py -v`

### Phase 4: Explicit invocation and injection

Files:

1. Update `pycodex/core/agent.py`
2. Add `pycodex/core/skills/injector.py`
3. Add tests under `tests/core/test_agent.py` and `tests/agent_harness/` targeted scenarios

Deliverables:

1. Resolve explicit mentions before each model sample cycle boundary (user turn entry point).
2. Inject selected skills as synthetic user messages in deterministic order.
3. Persist injected messages via existing session history path.

Verification:

1. `pytest tests/core/test_agent.py -v`
2. `pytest tests/agent_harness/test_smoke.py -v`
3. Targeted new harness scenarios for explicit mention, ambiguity, and missing skill file

### Phase 5: Dependency and approval integration

Files:

1. Update `pycodex/core/skills/resolver.py` (dependency checks)
2. Update `pycodex/core/tui_bridge.py` (if interactive dependency prompt path is added in same phase)
3. Update `pycodex/tools/orchestrator.py` or approval preview helpers for skill-script context
4. Add tests under `tests/tools/` and `tests/core/skills/`

Deliverables:

1. `env_var` dependency gate in resolver.
2. Skill-script contextual approval preview for shell commands.

Verification:

1. `pytest tests/tools/test_orchestrator.py -v`
2. Targeted `tests/core/skills/*` dependency cases

### Phase 6: Hardening and docs

Files:

1. Update `docs/ai/system-map.md` with skills architecture map.
2. Update `docs/ai/harness.md` with new harness scenarios.
3. Optional: add `docs/ai/memory.md` decisions after rollout.

Deliverables:

1. Architecture and test docs reflect shipped behavior.
2. Open issues and deferred items tracked explicitly.

Verification:

1. `ruff check . --fix`
2. `ruff format .`
3. Targeted `pytest`
4. `mypy --strict` for touched public type surfaces

## Test Matrix (Required)

### Unit

1. Frontmatter parsing and validation.
2. Sidecar parse fail-open behavior.
3. Root ordering and dedupe.
4. Mention extraction: `$name` in prose, path-linked form, mentions in code fences are excluded, trailing punctuation does not bleed into name.
5. Mention extraction: duplicate `$name` in same message produces exactly one resolved skill.
6. Injection payload formatting.
7. Conflict resolution: same name across scopes resolves by precedence, not marked ambiguous.
8. Conflict resolution: same name within same scope marked ambiguous.
9. `## Skills` section format: correct bullet format, short-description inclusion, truncation at 2000 chars with count suffix.
10. `## Skills` section: omitted entirely when no skills exist.

### Integration

1. Startup context includes compact `## Skills` section with correct format.
2. Startup context emits no `## Skills` section when skill set is empty.
3. Explicit mention injects only selected skill body.
4. Dependency failure injects `<skill-unavailable>` with correct reason; model turn continues.
5. Ambiguity injects `<skill-unavailable>` with correct reason; other skills in same turn still inject.
6. Missing skill file at injection time injects `<skill-unavailable>` with file-not-found reason.
7. `<skill-unavailable>` messages appear before `<skill>` messages in same turn.
8. Malformed skill does not crash turn.
9. Skill-script shell commands produce skill-aware approval preview.

### Harness/behavior

1. End-to-end explicit skill mention flow.
2. Ambiguous mention: `<skill-unavailable>` injected, model explains to user.
3. Dependency failure: `<skill-unavailable>` injected, model explains missing env var.
4. Resume/replay: injected skill messages are not re-injected on session resume.
5. Resume/replay: `<skill-unavailable>` messages from prior turn are preserved in history and not re-emitted.

### Rollout and Compatibility

1. No schema version bump required for v1.
2. Injected skill payloads are persisted as normal history items.
3. Existing CLI/TUI commands remain unchanged.
4. Default behavior when no skills exist: no-op, no warnings.

## Future Improvements

### V2 candidates

1. Optional model-invoked `Skill` tool path (secondary to explicit mention path).
2. MCP dependency install/login flow.
3. File watcher-based cache invalidation and dynamic discovery.
4. Protocol events for skills (`skill.applied`, `skill.warning`) with Python/TS lockstep updates.
5. Per-skill permission profiles attached to approval requests.

### V3 candidates

1. Forked execution mode for long-running specialist skills.
2. Dynamic activation by touched paths.
3. Ranking/retrieval heuristics for large skill catalogs.
4. Skill analytics and success/failure telemetry dashboards.

## Acceptance Criteria for Initial Release

1. Skills discovered from configured roots with deterministic ordering and dedupe.
2. Model sees compact `## Skills` metadata catalog at session startup; section is omitted when no skills exist.
3. Full skill body is injected only for explicitly selected skills, in mention-appearance order.
4. Ambiguity and dependency failures surface to the model as `<skill-unavailable>` messages, not silent skips.
5. `<skill-unavailable>` messages always precede `<skill>` messages in the same turn.
6. Session resume does not re-inject skill messages already present in history.
7. Observability log events emitted for load, inject, skip, and replay-skip actions.
8. Existing agent/tool/orchestrator contracts remain intact.
9. Required targeted tests and harness smoke pass.
