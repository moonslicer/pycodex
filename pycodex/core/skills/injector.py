"""Turn-time synthetic message injection for explicitly selected skills."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pycodex.core.skills.manager import SkillRegistry
from pycodex.core.skills.models import SkillMetadata
from pycodex.core.skills.resolver import resolve_skill_mentions

_log = logging.getLogger("pycodex.skills.injector")


@dataclass(frozen=True, slots=True)
class SkillInjectedMessage:
    """One synthetic user message to append before model sampling."""

    kind: Literal["skill", "unavailable"]
    name: str
    path: Path | None
    content: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SkillInjectionPlan:
    """Ordered injection payload for one user turn."""

    messages: tuple[SkillInjectedMessage, ...]


def build_skill_injection_plan(*, user_input: str, registry: SkillRegistry) -> SkillInjectionPlan:
    """Resolve mentions and build synthetic messages in deterministic order."""
    resolution = resolve_skill_mentions(user_input, registry)

    unavailable_messages: list[SkillInjectedMessage] = []
    for unresolved in resolution.unresolved:
        reason = _unavailable_reason(unresolved.reason, path=unresolved.mention.path)
        unavailable_messages.append(
            SkillInjectedMessage(
                kind="unavailable",
                name=unresolved.mention.name,
                path=unresolved.mention.path,
                content=_render_unavailable_message(
                    name=unresolved.mention.name,
                    reason=reason,
                ),
                reason=reason,
            )
        )
        _log.warning("skill.unavailable name=%s reason=%s", unresolved.mention.name, reason)

    skill_messages: list[SkillInjectedMessage] = []
    for skill in resolution.resolved:
        missing_env = _missing_required_env_var(skill)
        if missing_env is not None:
            unavailable_messages.append(
                SkillInjectedMessage(
                    kind="unavailable",
                    name=skill.name,
                    path=skill.path_to_skill_md,
                    content=_render_unavailable_message(name=skill.name, reason=missing_env),
                    reason=missing_env,
                )
            )
            _log.warning("skill.unavailable name=%s reason=%s", skill.name, missing_env)
            continue

        try:
            skill_text = skill.path_to_skill_md.read_text(encoding="utf-8")
        except OSError:
            reason = "file not found"
            unavailable_messages.append(
                SkillInjectedMessage(
                    kind="unavailable",
                    name=skill.name,
                    path=skill.path_to_skill_md,
                    content=_render_unavailable_message(name=skill.name, reason=reason),
                    reason=reason,
                )
            )
            _log.warning("skill.unavailable name=%s reason=%s", skill.name, reason)
            continue

        skill_messages.append(
            SkillInjectedMessage(
                kind="skill",
                name=skill.name,
                path=skill.path_to_skill_md,
                content=_render_skill_message(skill=skill, payload=skill_text),
            )
        )
        _log.info(
            "skill.injected name=%s scope=%s path=%s",
            skill.name,
            skill.scope,
            skill.path_to_skill_md,
        )

    return SkillInjectionPlan(messages=tuple(unavailable_messages + skill_messages))


def _render_skill_message(*, skill: SkillMetadata, payload: str) -> str:
    return "\n".join(
        [
            "<skill>",
            f"<name>{skill.name}</name>",
            f"<path>{skill.path_to_skill_md}</path>",
            payload,
            "</skill>",
        ]
    )


def _render_unavailable_message(*, name: str, reason: str) -> str:
    return "\n".join(
        [
            "<skill-unavailable>",
            f"<name>{name}</name>",
            f"<reason>{reason}</reason>",
            "</skill-unavailable>",
        ]
    )


def _unavailable_reason(reason: str, *, path: Path | None) -> str:
    if reason == "ambiguous":
        return "ambiguous name"
    if reason == "not_found" and path is not None:
        return "file not found"
    return "skill not found"


def _missing_required_env_var(skill: SkillMetadata) -> str | None:
    dependencies = skill.dependencies
    if dependencies is None:
        return None
    for env_dependency in dependencies.env_vars:
        if os.getenv(env_dependency.name):
            continue
        return f"missing required env var: {env_dependency.name}"
    return None
