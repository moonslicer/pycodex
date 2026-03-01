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
