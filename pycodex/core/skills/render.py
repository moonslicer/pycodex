"""Rendering helpers for model-visible skills metadata."""

from __future__ import annotations

from collections.abc import Sequence

from pycodex.core.skills.models import SkillMetadata

_SKILLS_HEADER = "\n".join(
    [
        "## Skills",
        "",
        "The following skills are available. Mention `$skill-name` to invoke a skill.",
        "Use only skills listed here. Do not guess skill names.",
        "",
    ]
)


def render_skills_section(
    skills: Sequence[SkillMetadata],
    *,
    max_chars: int = 2_000,
) -> str | None:
    """Render the compact v1 skills catalog section."""
    if not skills:
        return None

    bullets = [_render_skill_bullet(skill) for skill in skills]
    full_section = _SKILLS_HEADER + "\n".join(bullets)
    if len(full_section) <= max_chars:
        return full_section

    for keep_count in range(len(bullets), -1, -1):
        remaining = len(bullets) - keep_count
        suffix = f"(and {remaining} more — use $skill-name by exact name to invoke)"
        parts: list[str] = [_SKILLS_HEADER]
        if keep_count > 0:
            parts.append("\n".join(bullets[:keep_count]))
        parts.append(suffix)
        candidate = "\n".join(part for part in parts if part)
        if len(candidate) <= max_chars:
            return candidate

    # Should never happen with the current header and limit.
    return _SKILLS_HEADER[:max_chars]


def _render_skill_bullet(skill: SkillMetadata) -> str:
    if skill.short_description is None:
        return f"- {skill.name}: {skill.description}"
    return f"- {skill.name}: {skill.description} — {skill.short_description}"
