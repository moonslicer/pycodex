from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pycodex.core.agent_profile import CODEX_PROFILE, AgentProfile, load_profile_from_toml


def test_codex_profile_defaults() -> None:
    assert CODEX_PROFILE.name == "codex"
    assert "AGENTS.md" in CODEX_PROFILE.instruction_filenames
    assert len(CODEX_PROFILE.instructions) > 50
    assert CODEX_PROFILE.enabled_tools is None


def test_agent_profile_is_frozen() -> None:
    profile = AgentProfile(name="x", instructions="y")
    with pytest.raises(FrozenInstanceError):
        profile.name = "z"  # type: ignore[misc]


def test_load_profile_from_toml_success(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    path.write_text(
        '\n'.join(
            [
                'name = "support"',
                'instructions = "You are a support assistant."',
                'instruction_filenames = ["SUPPORT.md", "TEAM.md"]',
                'enabled_tools = ["read_file", "shell"]',
            ]
        ),
        encoding="utf-8",
    )

    profile = load_profile_from_toml(path)

    assert profile == AgentProfile(
        name="support",
        instructions="You are a support assistant.",
        instruction_filenames=("SUPPORT.md", "TEAM.md"),
        enabled_tools=("read_file", "shell"),
    )


def test_load_profile_from_toml_missing_name_raises(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    path.write_text('instructions = "hello"', encoding="utf-8")

    with pytest.raises(ValueError, match="name"):
        load_profile_from_toml(path)


def test_load_profile_from_toml_missing_instructions_raises(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    path.write_text('name = "agent"', encoding="utf-8")

    with pytest.raises(ValueError, match="instructions"):
        load_profile_from_toml(path)


def test_load_profile_from_toml_optional_fields_default(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    path.write_text(
        '\n'.join(
            [
                'name = "minimal"',
                'instructions = "Minimal instructions."',
            ]
        ),
        encoding="utf-8",
    )

    profile = load_profile_from_toml(path)

    assert profile.instruction_filenames == ("AGENTS.md",)
    assert profile.enabled_tools is None
