"""Agent identity profiles and loaders."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """Defines agent identity independent of runtime configuration."""

    name: str
    instructions: str
    instruction_filenames: tuple[str, ...] = ("AGENTS.md",)
    enabled_tools: tuple[str, ...] | None = None


CODEX_PROFILE = AgentProfile(
    name="codex",
    instructions=(
        "You are an expert AI coding assistant operating in a terminal.\n"
        "You can read files, run shell commands, and edit code.\n"
        "Prefer making concrete changes over abstract explanations.\n"
        "Be concise, verify changes with tests, and avoid destructive actions "
        "without explicit user approval."
    ),
    instruction_filenames=("AGENTS.md",),
    enabled_tools=None,
)


def load_profile_from_toml(path: Path) -> AgentProfile:
    """Load an AgentProfile from a TOML file."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return load_profile_from_mapping(raw)


def load_profile_from_mapping(raw: Mapping[str, object]) -> AgentProfile:
    """Load an AgentProfile from an already-parsed mapping."""
    if not isinstance(raw, Mapping):
        raise ValueError("Profile TOML must decode to a table.")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Profile must define non-empty 'name'.")

    instructions = raw.get("instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError("Profile must define non-empty 'instructions'.")

    instruction_filenames_raw = raw.get("instruction_filenames", ("AGENTS.md",))
    instruction_filenames = _parse_string_tuple(
        field_name="instruction_filenames",
        value=instruction_filenames_raw,
    )
    if len(instruction_filenames) == 0:
        raise ValueError("'instruction_filenames' must not be empty.")

    enabled_tools_raw = raw.get("enabled_tools")
    enabled_tools: tuple[str, ...] | None
    if enabled_tools_raw is None:
        enabled_tools = None
    else:
        enabled_tools = _parse_string_tuple(
            field_name="enabled_tools",
            value=enabled_tools_raw,
        )

    return AgentProfile(
        name=name.strip(),
        instructions=instructions,
        instruction_filenames=instruction_filenames,
        enabled_tools=enabled_tools,
    )


def _parse_string_tuple(*, field_name: str, value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        parsed: list[str] = []
        for index, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"'{field_name}' entries must be non-empty strings (index {index})."
                )
            parsed.append(item)
        return tuple(parsed)
    raise ValueError(f"'{field_name}' must be a list or tuple of strings.")
