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
