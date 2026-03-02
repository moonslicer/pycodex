"""Configuration loading for pycodex."""

from __future__ import annotations

import os
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pycodex.approval.policy import ApprovalPolicy
from pycodex.approval.sandbox import SandboxPolicy
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
    compaction_threshold_ratio: float = 0.2
    compaction_context_window_tokens: int = 128_000
    compaction_strategy: str = "threshold_v1"
    compaction_implementation: str = "local_summary_v1"
    compaction_options: dict[str, dict[str, Any]] = Field(default_factory=dict)
    default_approval_policy: ApprovalPolicy = ApprovalPolicy.NEVER
    default_sandbox_policy: SandboxPolicy = SandboxPolicy.DANGER_FULL_ACCESS


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
    if value := os.getenv("PYCODEX_COMPACTION_THRESHOLD_RATIO"):
        parsed = _to_float(value)
        if parsed is not None:
            env["compaction_threshold_ratio"] = parsed
    if value := os.getenv("PYCODEX_COMPACTION_CONTEXT_WINDOW_TOKENS"):
        parsed = _to_int(value)
        if parsed is not None and parsed > 0:
            env["compaction_context_window_tokens"] = parsed
    if value := os.getenv("PYCODEX_COMPACTION_STRATEGY"):
        env["compaction_strategy"] = value
    if value := os.getenv("PYCODEX_COMPACTION_IMPLEMENTATION"):
        env["compaction_implementation"] = value
    if value := os.getenv("PYCODEX_DEFAULT_APPROVAL_POLICY"):
        env["default_approval_policy"] = value
    if value := os.getenv("PYCODEX_DEFAULT_SANDBOX_POLICY"):
        env["default_sandbox_policy"] = value

    return env


def load_config(
    config_path: Path | None = None,
    *,
    global_config_path: Path | None = None,
) -> Config:
    """Resolve runtime config with precedence: defaults < global < project < env."""
    global_path = global_config_path or _default_global_config_path()
    path = config_path or Path("pycodex.toml")
    global_toml_config = _load_toml_config(global_path)
    project_toml_config = _load_toml_config(path)
    env_config = _load_env_config()

    profile = CODEX_PROFILE
    global_toml_profile = global_toml_config.get("profile")
    if isinstance(global_toml_profile, dict):
        profile = load_profile_from_mapping(global_toml_profile)
    project_toml_profile = project_toml_config.get("profile")
    if isinstance(project_toml_profile, dict):
        profile = load_profile_from_mapping(project_toml_profile)

    instructions_override = env_config.pop("instructions", None)
    if isinstance(instructions_override, str) and instructions_override.strip():
        profile = replace(profile, instructions=instructions_override)

    merged: dict[str, Any] = {
        key: value for key, value in global_toml_config.items() if key != "profile"
    }
    merged.update({key: value for key, value in project_toml_config.items() if key != "profile"})
    merged.update(env_config)
    merged["profile"] = profile

    return Config.model_validate(merged)


def _default_global_config_path() -> Path:
    return Path.home() / ".pycodex" / "config.toml"


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None
