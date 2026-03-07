# Milestone 8 TODO — JSONL Session Ledger + Resume

## Goal
Establish one durable, append-only JSONL persistence system for session state and replay so resume, recovery, list, and archive all depend on one stable contract:
1. define and lock the rollout record schema,
2. persist session mutations through a single-writer recorder,
3. replay deterministically for `--resume`,
4. ship lifecycle commands (`session list/read/archive/unarchive`) on top of the same ledger.

## Architecture
```
Agent / Session mutations
  ├─ session.meta (open)
  ├─ history.item (user/assistant/tool items)
  ├─ turn.completed (usage snapshot from M7)
  ├─ compaction.applied (summary + replaced range + metadata)
  └─ session.closed (close summary)
           ↓
RolloutRecorder (single-writer queue)
  ├─ append-only JSONL write
  ├─ flush at turn boundaries
  └─ shutdown flush
           ↓
~/.pycodex/sessions/rollout-YYYYMMDD-<timestamp>-<thread_id>.jsonl
           ↓
RolloutReplay
  ├─ ordered read + schema validation
  ├─ soft-skip unknown record types
  ├─ hard-fail major schema mismatch
  └─ tolerate truncated final line
           ↓
CLI entrypoints
  ├─ --resume <thread-id|rollout-path>
  └─ session list|read|archive|unarchive
```

## Locked M8 Contracts (must remain stable)
- Append-only JSONL ledger as the source of truth for session durability.
- `schema_version` is present on every record.
- Unknown record types are soft-skipped with warning; major `schema_version` mismatch hard-fails resume.
- `session.closed` carries summary fields (last user message, turn count, token total, closed timestamp) so closed-session reads can avoid full replay.
- Flat filename layout is canonical:
  - active: `~/.pycodex/sessions/rollout-YYYYMMDD-<timestamp>-<thread_id>.jsonl`
  - archived: `~/.pycodex/archived_sessions/rollout-...jsonl`
- Replay rebuilds totals from persisted `turn.completed` records (no hidden recomputation).

## In Scope
- `pycodex/core/rollout_schema.py` (new)
- `pycodex/core/rollout_recorder.py` (new)
- `pycodex/core/rollout_replay.py` (new)
- `pycodex/core/session.py` (wire recorder ownership + write points)
- `pycodex/core/agent.py` (emit persistence write points around turn lifecycle)
- `pycodex/core/compaction.py` (persist compaction application payload)
- `pycodex/__main__.py` (`--resume` and `session` subcommands wiring)
- `tests/core/test_rollout_schema.py` (new)
- `tests/core/test_rollout_recorder.py` (new)
- `tests/core/test_rollout_replay.py` (new)
- `tests/core/test_rollout_legacy_import.py` (new)
- `tests/e2e/test_session_resume.py` (new)
- `tests/e2e/test_session_archive.py` (new)
- `tests/test_main.py` (extend resume/session command coverage)

## Out of Scope
- Planner state persistence (M9 planner remains ephemeral).
- Web/network resiliency or caching changes (M10).
- Transport/server architecture changes (M11+).
- Compaction algorithm redesign (persist representation only).
- SQLite runtime store in M8 (optional index-only follow-up).

## Success Metrics

### Functional
- Multi-turn sessions create JSONL rollout files under `~/.pycodex/sessions/`.
- `--resume <id>` continues from reconstructed state and appends new records.
- Crash/truncation recovery replays to last valid record without corruption.
- `session list/read/archive/unarchive` operate only by moving/reading rollout files.

### Contract / Architecture
- One writer task per session recorder; no interleaved line writes.
- Replay order is deterministic and append-order preserving.
- Schema evolution behavior is explicit and tested:
  - unknown type => soft warning + continue,
  - major version mismatch => explicit failure.
- Legacy `.json` sessions import once, idempotently, with source marker.

### Quality Gates
- `.venv/bin/ruff check . --fix`
- `.venv/bin/ruff format .`
- `.venv/bin/mypy --strict pycodex/`
- `.venv/bin/pytest tests/ -v`

## TODO Tasks

- [ ] T1: Rollout schema contract (`core/rollout_schema.py`, `tests/core/test_rollout_schema.py`)
  - Define `RolloutItem` union with `schema_version` on each record.
  - Include record types: `session.meta`, `history.item`, `turn.completed`, `compaction.applied`, `session.closed`.
  - Add golden fixtures for each record type to lock JSONL contract shape.
  - Verify:
    - `.venv/bin/pytest tests/core/test_rollout_schema.py -q`

- [ ] T2: JSONL recorder service (`core/rollout_recorder.py`, `tests/core/test_rollout_recorder.py`)
  - Implement single-writer async recorder with queued ingestion.
  - Public API: `record(items)`, `flush()`, `shutdown()`.
  - Ensure per-session ownership (no global singleton).
  - Verify:
    - `.venv/bin/pytest tests/core/test_rollout_recorder.py -q`

- [ ] T3: Filesystem layout and resolver behavior (`core/rollout_recorder.py`, tests)
  - Implement flat path naming: `rollout-YYYYMMDD-<timestamp>-<thread_id>.jsonl`.
  - Support archive root move with unchanged filename.
  - Resolve latest rollout for `thread_id` by sortable filename semantics.
  - Verify:
    - `.venv/bin/pytest tests/core/test_rollout_recorder.py -k path -q`

- [ ] T4: Persistence write points (`core/session.py`, `core/agent.py`, `core/compaction.py`, tests)
  - Persist `session.meta` at open.
  - Persist `history.item` records for user/assistant/tool mutations.
  - Persist `turn.completed` usage snapshot from M7.
  - Persist `compaction.applied` summary payload, replaced range, and strategy/implementation metadata.
  - Persist `session.closed` on clean shutdown.
  - Verify:
    - `.venv/bin/pytest tests/core/test_rollout_recorder.py -k write_points -q`

- [ ] T5: Replay engine (`core/rollout_replay.py`, `tests/core/test_rollout_replay.py`)
  - Replay JSONL in order with per-record `schema_version` checks.
  - Soft-skip unknown record types with warning.
  - Hard-fail on major schema version mismatch.
  - Rebuild history/config snapshot and token totals from persisted records.
  - Tolerate truncated last line and mark missing `session.closed` as `incomplete`.
  - Verify:
    - `.venv/bin/pytest tests/core/test_rollout_replay.py -q`

- [ ] T6: Resume entrypoint (`__main__.py`, `tests/test_main.py`)
  - Add `--resume <thread-id|rollout-path>`.
  - Resolve latest rollout by `thread_id` when ID-only is passed.
  - Start session from replayed state and continue normal turn loop.
  - Verify:
    - `.venv/bin/pytest tests/test_main.py -k resume -q`

- [ ] T7: Session lifecycle commands (`__main__.py`, e2e tests)
  - Add `session list` (newest-first; id/date/turns/tokens/status).
  - Add `session read <id>` (prefer `session.closed`; fallback replay with `status: "incomplete"`).
  - Add `session archive <id>` and `session unarchive <id>` as file moves only.
  - Verify:
    - `.venv/bin/pytest tests/e2e/test_session_archive.py -q`

- [ ] T8: Durability and failure semantics (core + e2e)
  - Force `flush()` at turn boundaries and on clean shutdown.
  - Recover from truncated tail after crash.
  - Return explicit error codes: `rollout_not_found`, `schema_version_mismatch`, `replay_failure`.
  - Verify:
    - `.venv/bin/pytest tests/e2e/test_session_resume.py -k crash -q`

- [ ] T9: Legacy `.json` import bridge (`core/rollout_replay.py` or dedicated importer, tests)
  - On first resume, detect `~/.pycodex/sessions/<id>.json` and import to rollout JSONL.
  - Mark source as `session.meta.import_source = "legacy_json"`.
  - Ensure idempotent import (no duplicate rollout files on repeated resume).
  - Verify:
    - `.venv/bin/pytest tests/core/test_rollout_legacy_import.py -q`

- [ ] T10: Milestone lock-in gates and fixtures
  - Run focused contract tests:
    - `.venv/bin/pytest tests/core/test_rollout_schema.py tests/core/test_rollout_recorder.py tests/core/test_rollout_replay.py tests/e2e/test_session_resume.py tests/e2e/test_session_archive.py -q`
  - Run full quality gates:
    - `.venv/bin/ruff check . --fix`
    - `.venv/bin/ruff format .`
    - `.venv/bin/mypy --strict pycodex/`
    - `.venv/bin/pytest tests/ -v`

## Task Dependency Graph
```
T1 (schema) ──> T2 (recorder) ──> T4 (write points)
      │               │
      └──────> T5 (replay) ──> T6 (resume)
                       ├────> T7 (session commands)
                       ├────> T8 (durability/failure semantics)
                       └────> T9 (legacy import)

T4 + T6 + T7 + T8 + T9 ──> T10 (full lock-in gates)
```

## Milestone Verification
- `PYCODEX_FAKE_MODEL=1 .venv/bin/python -m pycodex "<multi-turn prompt sequence>"`
  - Confirm rollout file is created and append-only records accumulate.
- `PYCODEX_FAKE_MODEL=1 .venv/bin/python -m pycodex --resume <thread_id> "<next prompt>"`
  - Confirm replayed context continues and new records append to the same rollout lineage.
- Simulate crash mid-write (truncate last JSONL line), then run resume:
  - Confirm replay skips invalid tail and resumes from last valid record.
- `PYCODEX_FAKE_MODEL=1 .venv/bin/python -m pycodex session archive <thread_id>`
- `PYCODEX_FAKE_MODEL=1 .venv/bin/python -m pycodex session unarchive <thread_id>`
  - Confirm move-only behavior and roundtrip visibility.

## Completion Checklist
- [ ] T1 complete
- [ ] T2 complete
- [ ] T3 complete
- [ ] T4 complete
- [ ] T5 complete
- [ ] T6 complete
- [ ] T7 complete
- [ ] T8 complete
- [ ] T9 complete
- [ ] T10 complete
- [ ] Ledger schema fixtures locked and reviewed
- [ ] All quality gates pass
- [ ] Manual M8 verification passes (or blockers documented)
