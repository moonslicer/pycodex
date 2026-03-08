from __future__ import annotations

from pathlib import Path

from pycodex.core.skills.discovery import SkillDiscoveryResult
from pycodex.core.skills.manager import SkillsManager
from pycodex.core.skills.models import SkillMetadata


def test_skills_manager_cache_uses_cwd_and_fingerprint(tmp_path: Path) -> None:
    calls: list[tuple[Path, tuple[Path | str, ...]]] = []

    skill_path = tmp_path / "repo" / "skill" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: a\ndescription: b\n---\n", encoding="utf-8")
    skill = SkillMetadata(
        name="a",
        description="b",
        short_description=None,
        path_to_skill_md=skill_path.resolve(),
        skill_root=skill_path.parent.resolve(),
        scope="repo",
    )

    def _discover(**kwargs: object) -> SkillDiscoveryResult:
        cwd = kwargs["cwd"]
        project_dirs = kwargs["project_skill_dirs"]
        assert isinstance(cwd, Path)
        assert isinstance(project_dirs, tuple)
        calls.append((cwd, project_dirs))
        return SkillDiscoveryResult(skills=(skill,), errors=(), ambiguous_names=frozenset())

    manager = SkillsManager(discover_fn=_discover)
    cwd = (tmp_path / "repo").resolve()

    first = manager.get_registry(cwd=cwd, config_fingerprint="alpha")
    second = manager.get_registry(cwd=cwd, config_fingerprint="alpha")
    third = manager.get_registry(cwd=cwd, config_fingerprint="beta")

    assert first is second
    assert first is not third
    assert len(calls) == 2


def test_skills_manager_force_reload_bypasses_cache(tmp_path: Path) -> None:
    call_count = 0

    skill_path = tmp_path / "repo" / "skill" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: a\ndescription: b\n---\n", encoding="utf-8")
    skill = SkillMetadata(
        name="a",
        description="b",
        short_description=None,
        path_to_skill_md=skill_path.resolve(),
        skill_root=skill_path.parent.resolve(),
        scope="repo",
    )

    def _discover(**_: object) -> SkillDiscoveryResult:
        nonlocal call_count
        call_count += 1
        return SkillDiscoveryResult(skills=(skill,), errors=(), ambiguous_names=frozenset())

    manager = SkillsManager(discover_fn=_discover)
    cwd = (tmp_path / "repo").resolve()

    manager.get_registry(cwd=cwd)
    manager.get_registry(cwd=cwd)
    manager.get_registry(cwd=cwd, force_reload=True)

    assert call_count == 2


def test_skills_manager_registry_excludes_ambiguous_name_lookup(tmp_path: Path) -> None:
    first_path = tmp_path / "first" / "SKILL.md"
    first_path.parent.mkdir(parents=True)
    first_path.write_text("---\nname: duplicate\ndescription: root\n---\n", encoding="utf-8")
    second_path = tmp_path / "second" / "SKILL.md"
    second_path.parent.mkdir(parents=True)
    second_path.write_text("---\nname: duplicate\ndescription: nested\n---\n", encoding="utf-8")

    first = SkillMetadata(
        name="duplicate",
        description="root",
        short_description=None,
        path_to_skill_md=first_path.resolve(),
        skill_root=first_path.parent.resolve(),
        scope="repo",
    )
    second = SkillMetadata(
        name="duplicate",
        description="nested",
        short_description=None,
        path_to_skill_md=second_path.resolve(),
        skill_root=second_path.parent.resolve(),
        scope="repo",
    )

    def _discover(**_: object) -> SkillDiscoveryResult:
        return SkillDiscoveryResult(
            skills=(first, second),
            errors=(),
            ambiguous_names=frozenset({"duplicate"}),
        )

    manager = SkillsManager(discover_fn=_discover)
    registry = manager.get_registry(cwd=tmp_path)

    assert "duplicate" not in registry.by_name
    assert registry.by_path[first.path_to_skill_md] is first
    assert registry.by_path[second.path_to_skill_md] is second


def test_skills_manager_registry_reports_model_invocation_disable(tmp_path: Path) -> None:
    skill_path = tmp_path / "skill" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: hidden\ndescription: hidden\n---\n", encoding="utf-8")
    hidden_skill = SkillMetadata(
        name="hidden",
        description="hidden",
        short_description=None,
        path_to_skill_md=skill_path.resolve(),
        skill_root=skill_path.parent.resolve(),
        scope="repo",
        disable_model_invocation=True,
    )

    def _discover(**_: object) -> SkillDiscoveryResult:
        return SkillDiscoveryResult(
            skills=(hidden_skill,),
            errors=(),
            ambiguous_names=frozenset(),
        )

    manager = SkillsManager(discover_fn=_discover)
    registry = manager.get_registry(cwd=tmp_path)

    assert registry.is_model_invocation_disabled("hidden") is True
    assert registry.is_model_invocation_disabled("missing") is False
