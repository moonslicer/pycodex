"""Configuration loading for pycodex."""

from __future__ import annotations

import os
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from pycodex.core.agent_profile import CODEX_PROFILE, AgentProfile, load_profile_from_mapping


class Config(BaseModel):
    """Runtime configuration resolved from defaults, TOML, and environment."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: str = "gpt-4.1-mini"
    api_key: str | None = None
    api_base_url: str | None = None
    cwd: Path = Path.cwd()
    profile: AgentProfile = CODEX_PROFILE
    project_doc_max_bytes: int = 32_768


def _load_toml_config(path: Path) -> dict[str, Any]:
    """Load optional TOML configuration from disk."""
    if not path.exists():
        return {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return raw


def _load_env_config() -> dict[str, Any]:
    """Load environment-based config values."""
    env: dict[str, Any] = {}

    if value := os.getenv("PYCODEX_MODEL"):
        env["model"] = value
    if value := os.getenv("OPENAI_API_KEY"):
        env["api_key"] = value
    if value := os.getenv("OPENAI_BASE_URL"):
        env["api_base_url"] = value
    if value := os.getenv("PYCODEX_CWD"):
        env["cwd"] = value
    if value := os.getenv("PYCODEX_INSTRUCTIONS"):
        env["instructions"] = value

    return env


def load_config(config_path: Path | None = None) -> Config:
    """Resolve runtime config with precedence: defaults < TOML < env."""
    path = config_path or Path("pycodex.toml")
    toml_config = _load_toml_config(path)
    env_config = _load_env_config()

    profile = CODEX_PROFILE
    toml_profile = toml_config.get("profile")
    if isinstance(toml_profile, dict):
        profile = load_profile_from_mapping(toml_profile)

    instructions_override = env_config.pop("instructions", None)
    if isinstance(instructions_override, str) and instructions_override.strip():
        profile = replace(profile, instructions=instructions_override)

    merged: dict[str, Any] = {
        key: value for key, value in toml_config.items() if key != "profile"
    }
    merged.update(env_config)
    merged["profile"] = profile

    return Config.model_validate(merged)
