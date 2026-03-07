# M6 Decisions Log

## T1 — AgentProfile base model

### What changed
- Added `pycodex/core/agent_profile.py` with:
  - frozen `AgentProfile` dataclass,
  - built-in `CODEX_PROFILE`,
  - `load_profile_from_toml(path)` loader with validation.
- Added `tests/core/test_agent_profile.py` covering:
  - default profile shape,
  - dataclass immutability,
  - successful TOML parsing,
  - missing required-field validation,
  - optional-field defaults.

### Ambiguous decisions and resolutions
- Should `instruction_filenames` allow an empty list?
  - Resolution: no. The loader raises `ValueError` for empty lists to avoid a silent "no lookup ever" configuration mistake.
- Should loader strip `instructions` content?
  - Resolution: no. Validation requires non-empty trimmed content, but stored content is preserved exactly to avoid changing user-authored prompt formatting.

## T2 — Config profile integration

### What changed
- Updated `pycodex/core/config.py` to add:
  - `profile: AgentProfile = CODEX_PROFILE`,
  - `project_doc_max_bytes: int = 32768`.
- Added TOML profile resolution from `[profile]` using `load_profile_from_mapping(...)`.
- Added `PYCODEX_INSTRUCTIONS` environment override that replaces only `profile.instructions`.
- Extended `tests/core/test_config.py` to cover default profile fields, TOML profile loading, and env instruction override behavior.
- Refactored `agent_profile.py` with `load_profile_from_mapping(...)` so parsed profile tables can be reused without temporary files.

### Ambiguous decisions and resolutions
- Should TOML profile parsing reuse the file loader or add a mapping loader?
  - Resolution: add `load_profile_from_mapping(...)` to avoid fake temp files and keep validation logic centralized.
- Should `PYCODEX_INSTRUCTIONS` override the whole profile?
  - Resolution: no. It overrides instructions only and preserves profile identity (`name`, `instruction_filenames`, `enabled_tools`).

## T3 — Session system-context mutation APIs

### What changed
- Updated `pycodex/core/session.py`:
  - added `append_system_message(text)`,
  - added `prepend_items(items)`.
- Extended `tests/core/test_session.py` for:
  - system-message append behavior,
  - prepend ordering behavior with existing history.

### Ambiguous decisions and resolutions
- Should `prepend_items` deduplicate existing system items?
  - Resolution: no. Prepend should be a simple ordered mutation; deduplication policy belongs to higher-level context assembly, not session storage.

## T4 — ModelClient `instructions` forwarding

### What changed
- Updated `pycodex/core/model_client.py`:
  - `ModelClient.stream(...)` now accepts `instructions: str = ""`,
  - request payload includes `instructions` only when non-empty.
- Extended `tests/core/test_model_client.py` with explicit assertions for:
  - omission of `instructions` on empty string,
  - inclusion of `instructions` for non-empty values.

### Ambiguous decisions and resolutions
- Should empty instructions be sent as `instructions=\"\"` or omitted?
  - Resolution: omit the field entirely for empty strings to avoid accidental blanking semantics at the API layer and keep payload minimal.

## T5 — Hierarchical project-doc loader

### What changed
- Added `pycodex/core/project_doc.py` with:
  - `find_git_root(start)`,
  - `load_project_instructions(cwd, filenames, max_bytes)`,
  - deterministic root->cwd traversal and UTF-8-safe truncation.
- Added `tests/core/test_project_doc.py` covering:
  - no-repo fallback behavior,
  - root->cwd ordering,
  - missing-file `None` return,
  - truncation marker behavior,
  - unreadable-file skip,
  - custom filename handling.

### Ambiguous decisions and resolutions
- What should happen for `max_bytes <= 0`?
  - Resolution: return `None` (treat as disabled loader output) instead of returning an empty/truncated marker string.
- Should unreadable files fail the full load?
  - Resolution: no. Unreadable files are skipped so sibling/lower-level docs can still load.

## T6 — Initial context assembly

### What changed
- Added `pycodex/core/initial_context.py` with:
  - `build_initial_context(config)` ordering:
    1. policy context,
    2. project instructions,
    3. environment context.
  - `_policy_context(...)` handling for approval/sandbox metadata,
  - `_env_context(...)` with cwd/shell/os/python details.
- Added `tests/core/test_initial_context.py` covering:
  - default env-only context,
  - non-default policy context inclusion,
  - default and custom profile filename loading,
  - required item ordering.

### Ambiguous decisions and resolutions
- Should environment context be optional when no docs/policy are present?
  - Resolution: no. Environment context is always included to provide deterministic runtime facts at session start.
- Should policy context depend on `Config` owning policy fields directly?
  - Resolution: no hard dependency. `_policy_context` reads attributes dynamically to keep this layer usable while policy fields remain CLI runtime concerns.

## T7 — Agent wiring for initial context + profile instructions

### What changed
- Updated `pycodex/core/agent.py`:
  - injects initial context once per session before first user message,
  - threads `profile.instructions` into `model_client.stream(...)`,
  - extends model-client protocol with optional `instructions` parameter.
- Updated `pycodex/core/session.py`:
  - added internal initial-context state (`has_initial_context`, `mark_initial_context_injected`).
- Extended `tests/core/test_agent.py`:
  - verifies single-injection behavior across multiple turns,
  - verifies profile instructions are passed into model streaming.

### Ambiguous decisions and resolutions
- Where should "context already injected" state live?
  - Resolution: in `Session`, not `Agent`, so repeated helper-based turns (new `Agent` instances over one session) still avoid duplicate injection.
- Should context be injected when `Session.config` is absent?
  - Resolution: no. Skip injection and send empty `instructions` to preserve behavior for config-less session tests and compatibility call paths.

## T8 — CLI profile/instruction overrides

### What changed
- Updated `pycodex/__main__.py` to add CLI flags:
  - `--profile`,
  - `--profile-file`,
  - `--instructions`,
  - `--instructions-file`.
- Added profile resolution helpers with precedence and validation:
  - built-in profile lookup,
  - profile TOML loading,
  - instructions text/file override loading,
  - non-empty instructions enforcement.
- Wired override-aware config resolution through text/json/tui runtime paths.
- Updated `pycodex/core/fake_model_client.py` to accept optional `instructions` for compatibility with new model-client protocol shape.
- Extended `tests/test_main.py` with profile/instructions parsing and resolution assertions.

### Ambiguous decisions and resolutions
- Should CLI overrides always be forwarded to `_run_prompt`/`_run_prompt_json`/`_run_tui_mode`?
  - Resolution: only when override flags are present, preserving backward compatibility for existing monkeypatched tests expecting prior call signatures.
- Where should profile/instructions precedence be enforced?
  - Resolution: centralized in `_resolve_profile_override(...)` so all runtime modes share one decision path.

## T9 — Full gates and milestone verification

### What changed
- Ran milestone-focused verification suites for M6 components.
- Ran full quality gates:
  - `.venv/bin/ruff check . --fix`
  - `.venv/bin/ruff format .`
  - `.venv/bin/mypy --strict pycodex/`
  - `.venv/bin/pytest tests/ -v`
- Addressed gate regressions by updating harness/e2e fake model clients to accept
  `stream(..., instructions: str = "")`, matching the updated model-client protocol.
- Updated `todo-m6.md` completion checklist to mark all M6 tasks complete.

### Ambiguous decisions and resolutions
- Should compatibility fixes for test doubles be deferred to a separate follow-up?
  - Resolution: no. Applied immediately within T9 so full-repo hard gates pass atomically for the milestone.
- How to run milestone verification commands in a network-restricted local environment?
  - Resolution: execute with `PYCODEX_FAKE_MODEL=1` to validate CLI/runtime wiring without external API dependency.
