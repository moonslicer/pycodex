from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest
from pycodex.core.skills.injector import build_skill_injection_plan
from pycodex.core.skills.manager import SkillRegistry
from pycodex.core.skills.models import SkillDependencies, SkillEnvVarDependency, SkillMetadata


def test_build_skill_injection_plan_includes_unavailable_before_skill(tmp_path: Path) -> None:
    skill_path = tmp_path / "alpha" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: alpha\ndescription: Alpha\n---\nbody\n", encoding="utf-8")

    alpha = _skill("alpha", skill_path)
    registry = _registry((alpha,))
    missing = tmp_path / "missing" / "SKILL.md"

    plan = build_skill_injection_plan(
        user_input=f"[$missing]({missing}) and $alpha",
        registry=registry,
    )

    assert [message.kind for message in plan.messages] == ["unavailable", "skill"]
    assert plan.messages[0].reason == "file not found"
    assert "<skill-unavailable>" in plan.messages[0].content
    assert "<skill>" in plan.messages[1].content
    assert "<name>alpha</name>" in plan.messages[1].content


def test_build_skill_injection_plan_maps_ambiguous_reason(tmp_path: Path) -> None:
    duplicate = _skill("duplicate", tmp_path / "dup" / "SKILL.md")
    registry = _registry((duplicate,), ambiguous_names=frozenset({"duplicate"}))

    plan = build_skill_injection_plan(user_input="$duplicate", registry=registry)

    assert len(plan.messages) == 1
    assert plan.messages[0].kind == "unavailable"
    assert plan.messages[0].reason == "ambiguous name"
    assert "<reason>ambiguous name</reason>" in plan.messages[0].content


def test_build_skill_injection_plan_reports_missing_file_for_resolved_skill(tmp_path: Path) -> None:
    skill_path = tmp_path / "gone" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: gone\ndescription: Gone\n---\n", encoding="utf-8")
    gone = _skill("gone", skill_path)
    skill_path.unlink()

    registry = _registry((gone,))
    plan = build_skill_injection_plan(user_input="$gone", registry=registry)

    assert len(plan.messages) == 1
    assert plan.messages[0].kind == "unavailable"
    assert plan.messages[0].reason == "file not found"


def test_build_skill_injection_plan_reports_missing_required_env_var(tmp_path: Path) -> None:
    needs_path = tmp_path / "needs" / "SKILL.md"
    needs_path.parent.mkdir(parents=True)
    needs_path.write_text("---\nname: needs\ndescription: Needs\n---\n", encoding="utf-8")
    ok_path = tmp_path / "ok" / "SKILL.md"
    ok_path.parent.mkdir(parents=True)
    ok_path.write_text("---\nname: ok\ndescription: Ok\n---\n", encoding="utf-8")

    needs = _skill(
        "needs",
        needs_path,
        dependencies=SkillDependencies(env_vars=(SkillEnvVarDependency(name="MISSING_ENV"),)),
    )
    ok = _skill("ok", ok_path)
    registry = _registry((needs, ok))

    plan = build_skill_injection_plan(user_input="$needs and $ok", registry=registry)

    assert [message.kind for message in plan.messages] == ["unavailable", "skill"]
    assert plan.messages[0].reason == "missing required env var: MISSING_ENV"
    assert "<reason>missing required env var: MISSING_ENV</reason>" in plan.messages[0].content
    assert "<name>ok</name>" in plan.messages[1].content


def test_build_skill_injection_plan_injects_when_required_env_is_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    needs_path = tmp_path / "needs" / "SKILL.md"
    needs_path.parent.mkdir(parents=True)
    needs_path.write_text("---\nname: needs\ndescription: Needs\n---\n", encoding="utf-8")
    monkeypatch.setenv("AVAILABLE_ENV", "1")

    needs = _skill(
        "needs",
        needs_path,
        dependencies=SkillDependencies(env_vars=(SkillEnvVarDependency(name="AVAILABLE_ENV"),)),
    )
    registry = _registry((needs,))
    plan = build_skill_injection_plan(user_input="$needs", registry=registry)

    assert len(plan.messages) == 1
    assert plan.messages[0].kind == "skill"


def _skill(
    name: str,
    skill_path: Path,
    *,
    dependencies: SkillDependencies | None = None,
) -> SkillMetadata:
    resolved = skill_path.resolve()
    return SkillMetadata(
        name=name,
        description=f"{name} description",
        short_description=None,
        path_to_skill_md=resolved,
        skill_root=resolved.parent,
        scope="repo",
        dependencies=dependencies,
    )


def _registry(
    skills: tuple[SkillMetadata, ...],
    *,
    ambiguous_names: frozenset[str] = frozenset(),
) -> SkillRegistry:
    by_name = {skill.name: skill for skill in skills if skill.name not in ambiguous_names}
    by_path = {skill.path_to_skill_md: skill for skill in skills}
    return SkillRegistry(
        skills=skills,
        errors=(),
        ambiguous_names=ambiguous_names,
        by_name=MappingProxyType(by_name),
        by_path=MappingProxyType(by_path),
    )
