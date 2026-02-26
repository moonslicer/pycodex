"""Configuration loading for pycodex."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    """Runtime configuration resolved from defaults, TOML, and environment."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: str = "gpt-4.1-mini"
    api_key: str | None = None
    api_base_url: str | None = None
    cwd: Path = Path.cwd()


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

    return env


def load_config(config_path: Path | None = None) -> Config:
    """Resolve runtime config with precedence: defaults < TOML < env."""
    path = config_path or Path("pycodex.toml")
    merged: dict[str, Any] = {}
    merged.update(_load_toml_config(path))
    merged.update(_load_env_config())
    return Config.model_validate(merged)
