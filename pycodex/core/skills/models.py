"""Skill metadata domain models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SkillScope = Literal["repo", "user", "system"]


@dataclass(frozen=True, slots=True)
class SkillEnvVarDependency:
    """Single required environment variable for a skill."""

    name: str


@dataclass(frozen=True, slots=True)
class SkillDependencies:
    """Dependency metadata parsed from sidecar policy files."""

    env_vars: tuple[SkillEnvVarDependency, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    """Canonical metadata for a discovered skill."""

    name: str
    description: str
    short_description: str | None
    path_to_skill_md: Path
    skill_root: Path
    scope: SkillScope
    dependencies: SkillDependencies | None = None
    allow_implicit_invocation: bool = False


@dataclass(frozen=True, slots=True)
class SkillLoadOutcome:
    """Bulk skill load result with non-fatal diagnostics."""

    skills: tuple[SkillMetadata, ...]
    errors: tuple[str, ...]
    disabled_paths: tuple[Path, ...]
