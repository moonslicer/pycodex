# Milestone 6 TODO — Instruction Context System (System Prompt + Developer Instructions)

## Goal
Implement a two-layer instruction system that makes model behavior deterministic and policy-aware:
1. pass base system instructions via the Responses API `instructions` field on every model call,
2. prepend one-time initial context (policy, project docs, environment) before the first user turn.

## Architecture
```
AgentProfile (identity)
  ├─ instructions                -> ModelClient.stream(..., instructions=...)
  ├─ instruction_filenames       -> project_doc loader filenames
  └─ enabled_tools (future use)

build_initial_context(config)
  1) policy context
  2) project docs (git root -> cwd, profile-driven filenames)
  3) environment context
        ↓
Session.prepend_items(initial_context)   (once)
```

## In Scope
- `pycodex/core/agent_profile.py` (new)
- `pycodex/core/project_doc.py` (new)
- `pycodex/core/initial_context.py` (new)
- `pycodex/core/config.py` (modify)
- `pycodex/core/session.py` (modify)
- `pycodex/core/model_client.py` (modify)
- `pycodex/core/agent.py` (modify)
- `pycodex/__main__.py` (modify)
- `tests/core/test_agent_profile.py` (new)
- `tests/core/test_project_doc.py` (new)
- `tests/core/test_initial_context.py` (new)
- `tests/core/test_session.py` (extend)
- `tests/core/test_model_client.py` (extend)
- `tests/core/test_agent.py` (extend)
- `tests/core/test_config.py` (extend)
- `tests/test_main.py` (extend)

## Out of Scope
- Plugin/profile discovery via entry points
- Per-model instruction templates/personality system
- Collaboration-mode or memory-tool instructions
- Skills injection (planned for M8)
- Session persistence/recovery of base instructions

## Success Metrics

### Functional
- `python -m pycodex "in one sentence, what is your role?"` reflects default coding-assistant identity.
- `python -m pycodex --instructions "You are a haiku generator." "hello"` overrides base instructions.
- `python -m pycodex --profile-file /tmp/profile.toml "what are you?"` loads a custom profile.
- Project instruction files are auto-discovered and injected from git root down to `cwd`.
- Custom profile `instruction_filenames` changes which docs are loaded.

### Architecture / Contract
- `AgentProfile` is frozen and has no framework imports.
- `Config` holds `profile: AgentProfile` (identity) instead of raw instruction strings.
- `ModelClient.stream()` accepts `instructions` explicitly and forwards it to API.
- `build_initial_context()` is the single assembly point and is deterministic for a fixed config/filesystem.
- `Session` remains the sole history mutator.

### Quality Gates
- `ruff check . --fix`
- `ruff format .`
- `mypy --strict pycodex/`
- `pytest tests/ -v`

## TODO Tasks

- [ ] T1: `core/agent_profile.py` — `AgentProfile`, `CODEX_PROFILE`, TOML loader
  - Add frozen `AgentProfile` dataclass: `name`, `instructions`, `instruction_filenames`, `enabled_tools`.
  - Add `CODEX_PROFILE` as default coding assistant profile.
  - Add `load_profile_from_toml(path: Path) -> AgentProfile` with validation for required fields.
  - Verify:
    - `pytest tests/core/test_agent_profile.py -v`
    - `python3 -c "from pycodex.core.agent_profile import CODEX_PROFILE; print(CODEX_PROFILE.name)"`

- [ ] T2: `core/config.py` — profile integration and limits
  - Add `profile: AgentProfile = CODEX_PROFILE`.
  - Add `project_doc_max_bytes: int = 32768`.
  - Support profile loading from `pycodex.toml` (`[profile]`) and env override for instructions only.
  - Verify:
    - `pytest tests/core/test_config.py -k "profile or instructions or project_doc_max_bytes" -v`

- [ ] T3: `core/session.py` — system-item mutation APIs
  - Add `append_system_message(text: str) -> None`.
  - Add `prepend_items(items: list[PromptItem]) -> None`.
  - Preserve `to_prompt()` copy semantics and ordering.
  - Verify:
    - `pytest tests/core/test_session.py -k "system or prepend" -v`

- [ ] T4: `core/model_client.py` — forward `instructions` to API
  - Extend `ModelClient.stream()` with `instructions: str = ""`.
  - Forward non-empty instructions to Responses API.
  - Keep system-role message items in `input` untouched.
  - Verify:
    - `pytest tests/core/test_model_client.py -k instructions -v`

- [ ] T5: `core/project_doc.py` — hierarchical instruction loader
  - Implement `find_git_root(start: Path) -> Path | None`.
  - Implement `load_project_instructions(cwd, filenames, max_bytes) -> str | None`.
  - Walk root->cwd, check filenames in-order at each directory level, concatenate with separator, cap by `max_bytes`.
  - Verify:
    - `pytest tests/core/test_project_doc.py -v`

- [ ] T6: `core/initial_context.py` — policy/docs/env context assembly
  - Implement `_policy_context(config) -> str | None`.
  - Implement `_env_context(cwd) -> str`.
  - Implement `build_initial_context(config) -> list[PromptItem]` with ordering:
    - policy context,
    - project docs via `config.profile.instruction_filenames`,
    - environment context.
  - Verify:
    - `pytest tests/core/test_initial_context.py -v`

- [ ] T7: `core/agent.py` — one-time initial-context injection + instructions threading
  - Prepend initial context once before first turn.
  - Pass `config.profile.instructions` to `model_client.stream()`.
  - Keep behavior stable for subsequent turns (no re-prepend).
  - Verify:
    - `pytest tests/core/test_agent.py -k "initial_context or instructions" -v`

- [ ] T8: `__main__.py` — CLI profile/instruction flags and precedence
  - Add flags:
    - `--profile`
    - `--profile-file`
    - `--instructions`
    - `--instructions-file`
  - Enforce mutual exclusivity (`profile` vs `profile-file`, `instructions` vs `instructions-file`).
  - Implement precedence:
    - `--instructions` > `--instructions-file` > `--profile-file` > `--profile` > config TOML > `CODEX_PROFILE`.
  - Verify:
    - `pytest tests/test_main.py -k "profile or instructions" -v`

- [ ] T9: Integration tests and full quality gates
  - Run milestone-focused tests:
    - `pytest tests/core/test_agent_profile.py tests/core/test_project_doc.py tests/core/test_initial_context.py -v`
    - `pytest tests/core/test_session.py tests/core/test_model_client.py tests/core/test_agent.py tests/core/test_config.py -k "profile or instructions or system or prepend or initial_context" -v`
    - `pytest tests/test_main.py -k "profile or instructions" -v`
  - Run full gates:
    - `ruff check . --fix`
    - `ruff format .`
    - `mypy --strict pycodex/`
    - `pytest tests/ -v`

## Task Dependency Graph
```
T1 (AgentProfile)        T5 (project_doc)
  └─> T2 (Config)          └─> T6 (initial_context)
       ├─> T3 (Session)    └─> T7 (Agent wiring)
       ├─> T4 (ModelClient)└─> T8 (CLI flags)
       └───────────────> T7

T3 + T4 + T6 + T8 ──> T9
```

## Milestone Verification
- `python -m pycodex "in one sentence, what is your role?"`
- `python -m pycodex --instructions "You are a haiku generator." "hello"`
- `python -m pycodex --profile-file /tmp/test-profile.toml "what are you?"`
- `pytest tests/core/test_project_doc.py -v`

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
- [ ] All quality gates pass
- [ ] Milestone verification commands pass (or runtime blocker documented)
