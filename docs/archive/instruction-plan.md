# Instruction Context Plan: System Prompt + Developer Instructions

## Context

**Problem**: pycodex currently sends no system prompt and no developer instructions to the model. `SystemMessageItem` is defined in `session.py` but has no append method and is never used. The model receives raw user messages, tool results, and assistant replies — but nothing telling it *who it is*, *what constraints apply*, or *what the project context is*.

**Generalization goal**: pycodex's agent loop, tool registry, and approval system are already generic. The instruction system should be too. Hardcoding a coding assistant identity directly into `config.py` and a filename like `"AGENTS.md"` directly into `project_doc.py` would make building a different agent on this framework require touching framework internals. Instead, agent identity is isolated into a single `AgentProfile` type — separate from runtime config.

**Reference**: OpenAI Codex (`~/Projects/codex`) solves this with a clean two-layer design:
1. `base_instructions` → sent as the Responses API `instructions` field (system prompt).
2. Developer instructions (policy, project docs, environment) → prepended to the `input` array as role=`"developer"` items assembled in `build_initial_context()`.

This plan adapts those patterns in idiomatic Python at pycodex's scale, with an added separation between agent identity (`AgentProfile`) and runtime config (`Config`).

---

## Goals

1. **Separate agent identity from runtime config.** Introduce `AgentProfile` — a small, frozen dataclass that defines what an agent *is*: its instructions, its instruction filenames, and its tool selection. `Config` holds a profile reference, not raw instruction strings. Building a different agent means defining a new profile, not touching framework code.

2. **Wire the `instructions` API field.** The OpenAI Responses API has a top-level `instructions` parameter that acts as the system prompt. pycodex currently ignores it. After this plan, every model request passes the active profile's instruction string.

3. **Ship a sensible default profile.** The built-in `CODEX_PROFILE` makes the default agent a coding assistant. Users can override via CLI flag, profile file, or inline `--instructions`.

4. **Load instruction files hierarchically, driven by the profile.** Walk from the nearest `.git` root down to `cwd` and concatenate any files matching the profile's `instruction_filenames`. The profile decides which filenames to look for — not a hardcoded constant in the loader.

5. **Inject environment context.** Tell the model the working directory, shell, and OS at session start so it can make contextually correct tool calls without asking.

6. **Inject policy context.** Translate the active `ApprovalPolicy` and `SandboxPolicy` into a brief human-readable instruction so the model understands the safety constraints it is operating under.

7. **Assemble initial context in one place.** A single `build_initial_context()` function collects all initial context items (policy, project docs, environment) in a defined order and returns a `list[PromptItem]`. The agent prepends this to the session once, before the first turn.

8. **Expose profile and instruction overrides via CLI.** Users can select a built-in profile with `--profile`, load a custom profile from a file with `--profile-file`, or override the active profile's instructions inline with `--instructions` or `--instructions-file`.

---

## Non-Goals

- **No plugin system or entry_points.** Profiles are defined in Python or loaded from TOML files. No dynamic import, no package discovery, no "profile marketplace."
- **No per-model instruction templates or personality system.** Codex supports a `{{ personality }}` placeholder in model-specific instruction templates. pycodex profiles carry a single instructions string; per-model variants are M7+ polish.
- **No collaboration-mode or memory-tool instructions.** Codex injects instructions for its memory tool and collaboration mode. pycodex has neither.
- **No skills section injection.** Skills are planned for M8; this plan does not stub them. Skills will inject via `build_initial_context()` when M8 ships.
- **No commit attribution injection.** Git co-author trailers in initial context are deferred.
- **No instruction file size enforcement in session.** The 32 KiB cap applies at the `project_doc.py` loader level only; no additional truncation inside Session.
- **No conversation-history persistence of base instructions.** Codex can recover `base_instructions` from serialized conversation history. pycodex always reconstructs from config at startup.
- **No schema version or stability guarantee for initial context format.** This plan does not add event types for context injection; the initial context is invisible to protocol consumers.

---

## Architecture

### Two Layers + Profile

```
┌──────────────────────────────────────────────────────────────┐
│  AgentProfile (agent identity — who the agent is)            │
│  name, instructions, instruction_filenames, enabled_tools    │
│  Built-in: CODEX_PROFILE (coding assistant, ["AGENTS.md"])   │
│  Custom:   loaded from TOML file or defined in Python        │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│  Layer 1 — base instructions (system prompt)                 │
│  config.profile.instructions →                               │
│    ModelClient.stream(instructions=...)                       │
│    → ResponsesAPI { instructions: "..." }                    │
│  Override priority: --instructions > --instructions-file >   │
│    --profile-file > --profile > CODEX_PROFILE default        │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│  Layer 2 — initial context (system messages in input)        │
│  build_initial_context(config) → list[PromptItem]            │
│    1. policy_context   (ApprovalPolicy + SandboxPolicy)      │
│    2. project_docs     (config.profile.instruction_filenames)│
│    3. env_context      (cwd, shell, OS)                      │
│  Agent prepends these to Session once before first turn.     │
└──────────────────────────────────────────────────────────────┘
```

### New Files

| File | Purpose |
|---|---|
| `pycodex/core/agent_profile.py` | `AgentProfile` dataclass + `CODEX_PROFILE` built-in + TOML loader |
| `pycodex/core/project_doc.py` | Git-root discovery + configurable-filename hierarchical loader |
| `pycodex/core/initial_context.py` | `build_initial_context()` assembly function |

### Modified Files

| File | Change |
|---|---|
| `pycodex/core/config.py` | Add `profile: AgentProfile = CODEX_PROFILE`, `project_doc_max_bytes: int = 32768` |
| `pycodex/core/session.py` | Add `append_system_message(text)`, `prepend_items(items)` |
| `pycodex/core/model_client.py` | Accept `instructions: str` in `stream()`, pass to API |
| `pycodex/core/agent.py` | Call `build_initial_context()` and `session.prepend_items()` before first turn; pass `config.profile.instructions` to stream |
| `pycodex/__main__.py` | Add `--profile`, `--profile-file`, `--instructions`, `--instructions-file` flags |

### Data Flow

```
Startup
  load_config()
    → Config.profile  (CODEX_PROFILE default, or --profile / --profile-file)
    → profile.instructions may be overridden by --instructions / --instructions-file

Agent first-turn pre-flight
  build_initial_context(config) → list[PromptItem]
    ├── _policy_context(config)                           → SystemMessageItem | None
    ├── load_project_instructions(                        → SystemMessageItem | None
    │     config.cwd,
    │     filenames=config.profile.instruction_filenames,
    │     max_bytes=config.project_doc_max_bytes,
    │   )
    └── _env_context(config.cwd)                         → SystemMessageItem
  session.prepend_items(initial_context_items)

Per-turn model call
  session.to_prompt() → list[PromptItem]
  model_client.stream(messages, tools, instructions=config.profile.instructions)
    → ResponsesAPI { instructions: ..., input: [sys_items…, user, asst, …], tools: … }
```

---

## Success Metrics

### Functional

- `python -m pycodex "what are you?"` — responds as coding assistant (CODEX_PROFILE default). No explicit persona in the user message.
- `python -m pycodex --instructions "You are a pirate." "say hello"` — inline override works.
- `python -m pycodex --profile-file support-agent.toml "hello"` — loads custom profile, model identity reflects it.
- `python -m pycodex "what directory are you running in?"` — answers from env context injection, no tool call.
- `AGENTS.md` present in project hierarchy → content appears in initial context (verified by test, not live call).
- Custom profile with `instruction_filenames = ["SUPPORT.md"]` → loads `SUPPORT.md` instead of `AGENTS.md`.

### Architecture / Contract

- `AgentProfile` is a frozen dataclass — immutable after construction; no shared mutable state.
- `AgentProfile` has no imports from `agent.py`, `session.py`, `model_client.py`, or `config.py` — it is a pure data type with no framework dependencies.
- `config.profile.instructions` is the single source of truth for the base system prompt; `ModelClient.stream()` receives it as a parameter, never reads `Config` directly.
- `build_initial_context()` is a pure function: given a `Config`, returns a deterministic `list[PromptItem]`. No I/O side effects; callers own the I/O.
- `load_project_instructions()` takes `filenames` as a parameter — no hardcoded filename constants at the call site.
- `Session.prepend_items()` preserves the invariant that `Session` is the sole history mutator.

### Quality Gates

- `ruff check . --fix`
- `ruff format .`
- `mypy --strict pycodex/`
- `pytest tests/ -v`

### Milestone Verification

```bash
# Default profile: coding assistant identity
python -m pycodex "in one sentence, what is your role?"

# Inline override
python -m pycodex --instructions "You are a haiku generator." "hello"

# Custom profile via file
cat > /tmp/test-profile.toml << 'EOF'
name = "test"
instructions = "You are a test agent."
instruction_filenames = ["TEST.md"]
EOF
python -m pycodex --profile-file /tmp/test-profile.toml "what are you?"

# Instruction file discovery (test, not live call)
pytest tests/core/test_project_doc.py -v
```

---

## TODO Tasks

### T0: `AgentProfile` dataclass + `CODEX_PROFILE` + TOML loader

**Files**: `pycodex/core/agent_profile.py` (new)

Define a frozen dataclass with no framework dependencies:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import tomllib

@dataclass(frozen=True)
class AgentProfile:
    """Defines agent identity: who the agent is and how it discovers context.

    Kept separate from Config (which holds runtime concerns: model, policies, cwd).
    All fields are immutable after construction.
    """
    name: str
    instructions: str
    instruction_filenames: tuple[str, ...] = ("AGENTS.md",)
    enabled_tools: tuple[str, ...] | None = None  # None = all registered tools

CODEX_PROFILE = AgentProfile(
    name="codex",
    instructions=(
        "You are an expert AI coding assistant operating in a terminal.\n"
        "You have access to tools for reading files, running shell commands, "
        "writing and editing code, listing directories, and searching file contents.\n"
        "Prefer making changes over explaining them. Be concise. "
        "Confirm before destructive or wide-impact operations.\n"
        "Output code in fenced blocks. No unnecessary preambles."
    ),
    instruction_filenames=("AGENTS.md",),
    enabled_tools=None,
)

def load_profile_from_toml(path: Path) -> AgentProfile:
    """Load an AgentProfile from a TOML file.

    Expected format:
        name = "my-agent"
        instructions = "You are ..."
        instruction_filenames = ["MYAGENT.md"]   # optional
        enabled_tools = ["read_file", "shell"]   # optional; omit for all tools
    """
```

**Depends on**: nothing (no framework imports)

**Verify**:
```bash
python3 -c "
from pycodex.core.agent_profile import CODEX_PROFILE
assert CODEX_PROFILE.name == 'codex'
assert 'AGENTS.md' in CODEX_PROFILE.instruction_filenames
assert len(CODEX_PROFILE.instructions) > 50
print('OK')
"
pytest tests/core/test_agent_profile.py -q
# Tests:
# - CODEX_PROFILE has correct fields
# - AgentProfile is frozen (mutation raises FrozenInstanceError)
# - load_profile_from_toml: valid file → correct AgentProfile
# - load_profile_from_toml: missing name or instructions → ValueError
# - load_profile_from_toml: optional fields default correctly
```

---

### T1: `Config.profile` field + `project_doc_max_bytes`

**Files**: `pycodex/core/config.py`

Replace the planned flat `instructions: str` field with `profile: AgentProfile`. `Config` becomes:

```python
from pycodex.core.agent_profile import AgentProfile, CODEX_PROFILE

class Config(BaseModel):
    model: str = "gpt-4.1-mini"
    api_key: str | None = None
    api_base_url: str | None = None
    cwd: Path = Path.cwd()
    profile: AgentProfile = CODEX_PROFILE        # replaces instructions: str
    project_doc_max_bytes: int = 32768
```

TOML loading: a `[profile]` section in `pycodex.toml` is parsed via `load_profile_from_toml()` and replaces the default. `PYCODEX_INSTRUCTIONS` env var may override `profile.instructions` inline, consistent with existing env-var pattern (produces a new frozen `AgentProfile` with the same other fields).

**Profile resolution precedence** (highest to lowest):
1. `--instructions` / `--instructions-file` CLI flag (inline text override — replaces instructions only)
2. `--profile-file` CLI flag (full profile from TOML)
3. `--profile` CLI flag (built-in name lookup)
4. `[profile]` section in `pycodex.toml`
5. `CODEX_PROFILE` default

**Depends on**: T0

**Verify**:
```bash
python3 -c "
from pycodex.core.config import load_config
from pycodex.core.agent_profile import CODEX_PROFILE
cfg = load_config()
assert cfg.profile == CODEX_PROFILE
assert cfg.project_doc_max_bytes == 32768
print('OK')
"
pytest tests/core/test_config.py -q
# New tests:
# - default config has CODEX_PROFILE
# - [profile] section in pycodex.toml loads correctly
# - PYCODEX_INSTRUCTIONS env var overrides profile.instructions only
```

---

### T2: `Session.append_system_message()` + `Session.prepend_items()`

**Files**: `pycodex/core/session.py`

`SystemMessageItem` is already defined as a TypedDict (role=`"system"`, content=`str`). Add two methods:

```python
def append_system_message(self, text: str) -> None:
    """Append a system/developer instruction to history."""
    self._history.append(SystemMessageItem(role="system", content=text))

def prepend_items(self, items: list[PromptItem]) -> None:
    """Prepend a list of items before the current history.

    Used by Agent to inject initial context (policy, project docs, env)
    before the first user message. Preserves the invariant that Session
    is the sole history mutator.
    """
    self._history = list(items) + self._history
```

The existing `to_prompt()` already returns all items in `_history` (including `SystemMessageItem`), so no changes needed there.

**Depends on**: T1

**Verify**:
```bash
pytest tests/core/test_session.py -q
# New tests:
# - prepend_items() puts items before existing history
# - append_system_message() adds a SystemMessageItem with correct content
# - to_prompt() includes prepended and appended system items at correct positions
```

---

### T3: `ModelClient.stream()` accepts and forwards `instructions`

**Files**: `pycodex/core/model_client.py`

Change `stream()` signature:

```python
async def stream(
    self,
    messages: list[PromptItem],
    tools: list[dict[str, Any]],
    instructions: str = "",
) -> AsyncIterator[ResponseEvent]:
```

Pass to API:
```python
stream = await responses.create(
    model=self._config.model,
    instructions=instructions or None,   # omit field entirely if empty
    input=input_items,
    tools=normalized_tools,
    stream=True,
)
```

System-role items in `messages` (from initial context) remain in `input` as `{"role": "system", "content": "..."}` entries — they are not extracted or deduplicated. Both layers reach the model independently, matching Codex's two-layer design.

**Depends on**: T1

**Verify**:
```bash
pytest tests/core/test_model_client.py -q
# New tests:
# - instructions="" omits the field from the API payload
# - non-empty instructions includes it in the API payload
# - system-role items in messages still appear in the input array
```

---

### T4: `core/project_doc.py` — configurable-filename hierarchical loader

**Files**: `pycodex/core/project_doc.py` (new)

```python
PROJECT_DOC_SEPARATOR = "\n--- project-doc ---\n"

def find_git_root(start: Path) -> Path | None:
    """Walk up from start until a .git directory is found. Returns None if not found."""

def load_project_instructions(
    cwd: Path,
    filenames: Sequence[str] = ("AGENTS.md",),
    max_bytes: int = 32768,
) -> str | None:
    """Walk from git root down to cwd, concatenating matched instruction files.

    Checks each filename in `filenames` at each directory level, in order.
    Returns None if no files are found anywhere.
    Concatenates entries with PROJECT_DOC_SEPARATOR.
    Total output is capped at max_bytes (UTF-8 encoded size).
    """
```

**Walk algorithm**:
1. Find git root from `cwd`. Fall back to `cwd` if no `.git` found.
2. Collect all directory paths from root to `cwd` inclusive, in order.
3. For each directory, for each filename in `filenames` (in order): check existence, read if present.
4. Concatenate all found files with `PROJECT_DOC_SEPARATOR`.
5. Truncate to `max_bytes` at UTF-8 boundary; append `\n[truncated]` if truncated.
6. Return `None` if no files found.

Edge cases: unreadable files skipped (continue); `cwd == git_root` loads one level; path not under git root falls back to `cwd` only; `find_git_root` stops at filesystem root.

**Depends on**: nothing (pure stdlib: `pathlib`, `os`)

**Verify**:
```bash
pytest tests/core/test_project_doc.py -q
# Tests:
# - no .git root: loads from cwd only
# - git root above cwd: loads root→cwd in order
# - no matching files anywhere: returns None
# - content over max_bytes: truncated with marker
# - unreadable file: skipped, rest loaded
# - cwd == git root: single level, no duplication
# - multiple filenames: each checked at each level
# - custom filenames=["SUPPORT.md"]: loads SUPPORT.md, ignores AGENTS.md
```

---

### T5: `core/initial_context.py` — context builders + `build_initial_context()`

**Files**: `pycodex/core/initial_context.py` (new)

```python
def _env_context(cwd: Path) -> str:
    """cwd, shell (SHELL env or 'sh'), OS (sys.platform → human name), Python version."""

def _policy_context(config: "Config") -> str | None:
    """Human-readable policy summary.
    Returns None if all policies are at their defaults (avoids noise).
    """

def build_initial_context(config: "Config") -> list[PromptItem]:
    """Assemble initial context items in order:
      1. policy_context   — approval + sandbox constraints
      2. project_docs     — config.profile.instruction_filenames hierarchy
      3. env_context      — cwd, shell, OS

    Each non-None result becomes a SystemMessageItem.
    Returns empty list if nothing to inject.
    """
```

Key: project doc lookup is profile-driven, not hardcoded:
```python
docs = load_project_instructions(
    config.cwd,
    filenames=config.profile.instruction_filenames,
    max_bytes=config.project_doc_max_bytes,
)
```

**Depends on**: T1 (Config + AgentProfile), T4 (load_project_instructions)

**Verify**:
```bash
pytest tests/core/test_initial_context.py -q
# Tests:
# - default config, no instruction files: returns [] or [env_context] only
# - non-default approval policy: policy item present
# - instruction file exists with default profile: project doc item correct
# - custom profile with custom filenames: loads those files, not AGENTS.md
# - all three sources present: items in correct order
# - build_initial_context returns list[PromptItem] with role="system"
```

---

### T6: Wire `build_initial_context()` into `Agent`

**Files**: `pycodex/core/agent.py`

```python
if not self._context_injected:
    initial = build_initial_context(self._config)
    if initial:
        self._session.prepend_items(initial)
    self._context_injected = True
```

Pass profile instructions to model client:
```python
await self._model_client.stream(
    messages, tools,
    instructions=self._config.profile.instructions,
)
```

**Depends on**: T2 (prepend_items), T3 (instructions param), T5 (build_initial_context)

**Verify**:
```bash
pytest tests/core/test_agent.py -q
# New tests:
# - first run_turn: initial context prepended before user message
# - second run_turn: initial context NOT prepended again
# - profile.instructions passed through to model client stream call
# - custom profile: custom instructions reach the model client
# - empty initial context (no files, default policy): session unmodified, no crash
```

---

### T7: Profile + instruction override CLI flags

**Files**: `pycodex/__main__.py`

Four flags in precedence order (highest first):

```
--instructions TEXT           Override active profile's instructions inline.
--instructions-file PATH      Load instruction text from a file (override).
--profile-file PATH           Load a full AgentProfile from a TOML file.
--profile NAME                Select a built-in profile by name (default: codex).
```

**Mutual exclusion rules**:
- `--instructions` and `--instructions-file` are mutually exclusive.
- `--profile` and `--profile-file` are mutually exclusive.
- `--instructions` / `--instructions-file` may combine with `--profile` / `--profile-file`: they override only the profile's `instructions` field while keeping all other profile fields.

**Resolution logic**:
1. Resolve base profile: `--profile-file` (TOML load) or `--profile` (built-in lookup). Default: `CODEX_PROFILE`.
2. If `--instructions` or `--instructions-file` provided: replace `profile.instructions` with the override text, producing a new frozen `AgentProfile` with all other fields unchanged.
3. Validate final instructions string is non-empty; exit 1 with error if empty.
4. Unknown `--profile NAME` exits 1.
5. Unreadable `--profile-file` or `--instructions-file` exits 1.

**Depends on**: T0 (AgentProfile, load_profile_from_toml), T1 (Config.profile)

**Verify**:
```bash
python -m pycodex --profile codex "hello"              # uses CODEX_PROFILE
python -m pycodex --instructions "" "hello"            # exits 1, empty instructions
python -m pycodex --profile unknown_name "hello"       # exits 1, unknown profile
python -m pycodex --profile-file /nonexistent "hello"  # exits 1, unreadable file
python -m pycodex --profile-file p.toml --instructions "override" "hello"  # valid: uses p.toml profile with overridden instructions
pytest tests/test_main.py -k "profile or instructions" -q
```

---

### T8: Tests + quality gates

New test files:

| Test File | Covers |
|---|---|
| `tests/core/test_agent_profile.py` | `AgentProfile` dataclass, `CODEX_PROFILE`, `load_profile_from_toml()` (T0) |
| `tests/core/test_project_doc.py` | Loader cases including custom filenames (T4) |
| `tests/core/test_initial_context.py` | All builders + profile-driven doc lookup (T5) |
| `tests/core/test_session.py` | `append_system_message`, `prepend_items` (T2) |
| `tests/core/test_model_client.py` | `instructions` param handling (T3) |
| `tests/core/test_agent.py` | Context injection + instructions threading (T6) |
| `tests/test_main.py` | Profile + instruction flags (T7) |

All existing tests must continue to pass unchanged.

**Run full quality gates**:
```bash
ruff check . --fix
ruff format .
mypy --strict pycodex/
pytest tests/ -v
```

**Depends on**: T0–T7

---

## Task Dependency Graph

```
T0 (AgentProfile + CODEX_PROFILE + TOML loader)   T4 (project_doc.py, filenames param)
 └─► T1 (Config.profile field)                         │
       ├─► T2 (Session.prepend_items)                  │
       ├─► T3 (ModelClient instructions param)         │
       ├─► T7 (CLI flags)                              │
       └─► T5 (initial_context.py) ◄───────────────────┘

T2 ──┐
T3 ──┤► T6 (Agent wiring)
T5 ──┘

T6 ──► T8 (tests + quality gates)
T7 ──► T8
```

Execution order with maximum parallelism:
- **Round 1**: T0, T4 (independent)
- **Round 2**: T1 (after T0)
- **Round 3**: T2, T3, T7 (after T1); T5 (after T1 + T4)
- **Round 4**: T6 (after T2 + T3 + T5)
- **Round 5**: T8 (after T6 + T7)

---

## Codex Reference Map

| pycodex (this plan) | Codex counterpart | File |
|---|---|---|
| `AgentProfile.instructions` | `config.base_instructions` | `codex-rs/core/src/config/mod.rs:229` |
| `CODEX_PROFILE` | `model_info.get_model_instructions()` | `codex-rs/protocol/src/openai_models.rs:282` |
| `AgentProfile.instruction_filenames` | `project_doc_fallback_filenames` | `codex-rs/core/src/project_doc.rs:74` |
| `project_doc.py` | `project_doc.rs` | `codex-rs/core/src/project_doc.rs:74` |
| `initial_context.py::build_initial_context` | `codex.rs::build_initial_context` | `codex-rs/core/src/codex.rs:2977` |
| `_policy_context` | `DeveloperInstructions::from_policy()` | `codex-rs/protocol/src/models.rs:390` |
| `_env_context` | env context item in `build_initial_context` | `codex-rs/core/src/codex.rs:3053` |
| `session.prepend_items` | session_configuration initialization | `codex-rs/core/src/codex.rs:346` |
| `model_client.stream(instructions=)` | `ResponsesApiRequest { instructions }` | `codex-rs/core/src/client.rs:561` |
| `--profile-file` / `--instructions` | `config.base_instructions` override | `codex-rs/core/src/config/mod.rs:229` |

---

## Simplifications vs Full Codex

| Codex feature | pycodex approach | Rationale |
|---|---|---|
| Per-model instruction templates + `{{ personality }}` | `AgentProfile.instructions` (single string per profile) | One API target; per-model branching is over-engineering at this scale |
| `DeveloperInstructions` struct with rich type variants | Plain `SystemMessageItem` strings | Same wire format; type hierarchy adds no value here |
| `UserInstructions` XML-wrapped with `<INSTRUCTIONS>` | Plain string with `# Project instructions\n` prefix | XML wrapping is Codex-specific |
| `project_doc_fallback_filenames` (hardcoded list) | `AgentProfile.instruction_filenames` (profile-driven) | More principled: each agent defines its own filenames |
| Collaboration mode, memory tool, apps instructions | Not implemented | Features don't exist in pycodex |
| Recover `base_instructions` from serialized history | Always reconstruct from config at startup | Session persistence (M7) will handle this properly |
| `config.user_instructions` vs `config.developer_instructions` | Single `profile.instructions` | No multi-party instruction provenance distinction needed |

---

## Completion Checklist

- [ ] T0: `AgentProfile` dataclass + `CODEX_PROFILE` + `load_profile_from_toml()`
- [ ] T1: `Config.profile: AgentProfile = CODEX_PROFILE` + `project_doc_max_bytes`
- [ ] T2: `Session.append_system_message()` + `Session.prepend_items()`
- [ ] T3: `ModelClient.stream(instructions=)` + API field forwarding
- [ ] T4: `core/project_doc.py` with `filenames` parameter + full edge-case handling
- [ ] T5: `core/initial_context.py` with profile-driven doc lookup
- [ ] T6: `Agent` wiring — context injection guard + profile instructions threading
- [ ] T7: `--profile`, `--profile-file`, `--instructions`, `--instructions-file` CLI flags
- [ ] T8: All tests pass + all quality gates green
- [ ] Milestone verification commands pass
