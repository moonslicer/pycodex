from __future__ import annotations

from pathlib import Path

from pycodex.core.skills.models import SkillMetadata
from pycodex.core.skills.render import render_skills_section


def test_render_skills_section_omits_when_empty() -> None:
    assert render_skills_section(()) is None


def test_render_skills_section_renders_bullets_in_order() -> None:
    skills = (
        _skill("alpha", "Alpha description", None),
        _skill("beta", "Beta description", "Beta short"),
    )

    rendered = render_skills_section(skills)

    assert rendered is not None
    assert rendered.startswith("## Skills\n")
    assert (
        "To invoke a skill, emit `$skillname` in your response and the full skill will be provided."
        in rendered
    )
    assert "- alpha: Alpha description" in rendered
    assert "- beta: Beta description — Beta short" in rendered
    assert rendered.index("- alpha: Alpha description") < rendered.index(
        "- beta: Beta description — Beta short"
    )


def test_render_skills_section_truncates_with_remaining_count() -> None:
    skills = tuple(_skill(f"skill-{index}", "x" * 80, None) for index in range(10))

    rendered = render_skills_section(skills, max_chars=260)

    assert rendered is not None
    assert len(rendered) <= 260
    assert "(and " in rendered
    assert "more - emit $skillname by exact name to invoke)" in rendered


def test_render_skills_section_excludes_disable_model_invocation() -> None:
    skills = (
        _skill("alpha", "Alpha description", None),
        _skill("hidden", "Hidden description", None, disable_model_invocation=True),
    )

    rendered = render_skills_section(skills)

    assert rendered is not None
    assert "- alpha: Alpha description" in rendered
    assert "hidden" not in rendered


def _skill(
    name: str,
    description: str,
    short_description: str | None,
    *,
    disable_model_invocation: bool = False,
) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=description,
        short_description=short_description,
        path_to_skill_md=Path(f"/tmp/{name}/SKILL.md"),
        skill_root=Path(f"/tmp/{name}"),
        scope="repo",
        disable_model_invocation=disable_model_invocation,
    )
