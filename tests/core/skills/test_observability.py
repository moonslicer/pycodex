from __future__ import annotations

import logging
from pathlib import Path
from types import MappingProxyType

import pytest
from pycodex.core.skills.discovery import discover_skills
from pycodex.core.skills.injector import build_skill_injection_plan
from pycodex.core.skills.manager import SkillRegistry
from pycodex.core.skills.models import SkillMetadata


def test_discovery_logs_skill_loaded_event(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    _write_skill(repo / ".agents" / "skills" / "alpha", name="alpha", description="Alpha")

    caplog.set_level(logging.DEBUG, logger="pycodex.skills.discovery")
    discover_skills(cwd=repo, user_root=tmp_path / "none", system_root=tmp_path / "none")

    assert any("skill.loaded" in record.getMessage() for record in caplog.records)


def test_discovery_logs_dependency_warnings(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    skill_dir = repo / ".agents" / "skills" / "alpha"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: Alpha\ndependencies: invalid\n---\nbody\n",
        encoding="utf-8",
    )

    caplog.set_level(logging.WARNING, logger="pycodex.skills.discovery")
    discover_skills(cwd=repo, user_root=tmp_path / "none", system_root=tmp_path / "none")

    assert any("skill.load_warning" in record.getMessage() for record in caplog.records)


def test_discovery_rejects_paths_outside_allowed_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    skills_root = repo / ".agents" / "skills"
    skills_root.mkdir(parents=True)

    outside = tmp_path / "outside" / "escaped"
    _write_skill(outside, name="escaped", description="Escaped")
    (skills_root / "escape-link").symlink_to(outside, target_is_directory=True)

    result = discover_skills(cwd=repo, user_root=tmp_path / "none", system_root=tmp_path / "none")

    assert [skill.name for skill in result.skills] == []
    assert any("outside allowed root" in error for error in result.errors)


def test_injector_logs_unavailable_and_injected_events(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    skill_path = tmp_path / "alpha" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: alpha\ndescription: Alpha\n---\nbody\n", encoding="utf-8")
    registry = _registry((_skill("alpha", skill_path),))

    caplog.set_level(logging.INFO, logger="pycodex.skills.injector")
    build_skill_injection_plan(user_input="$missing and $alpha", registry=registry)

    messages = [record.getMessage() for record in caplog.records]
    assert any("skill.unavailable" in message for message in messages)
    assert any("skill.injected" in message for message in messages)


def _write_skill(skill_dir: Path, *, name: str, description: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nbody\n",
        encoding="utf-8",
    )


def _skill(name: str, skill_path: Path) -> SkillMetadata:
    resolved = skill_path.resolve()
    return SkillMetadata(
        name=name,
        description=f"{name} description",
        short_description=None,
        path_to_skill_md=resolved,
        skill_root=resolved.parent,
        scope="repo",
    )


def _registry(skills: tuple[SkillMetadata, ...]) -> SkillRegistry:
    by_name = {skill.name: skill for skill in skills}
    by_path = {skill.path_to_skill_md: skill for skill in skills}
    return SkillRegistry(
        skills=skills,
        errors=(),
        ambiguous_names=frozenset(),
        by_name=MappingProxyType(by_name),
        by_path=MappingProxyType(by_path),
    )
