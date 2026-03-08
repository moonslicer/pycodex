from __future__ import annotations

from pathlib import Path

from pycodex.core.skills.discovery import collect_skill_roots, discover_skills


def test_collect_skill_roots_preserves_precedence_and_dedupes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cwd = repo / "pkg" / "feature"
    cwd.mkdir(parents=True)
    (repo / ".git").mkdir()

    repo_root_skills = repo / ".agents" / "skills"
    repo_nested_skills = repo / "pkg" / ".agents" / "skills"
    repo_root_skills.mkdir(parents=True)
    repo_nested_skills.mkdir(parents=True)

    user_root = tmp_path / "user-skills"
    user_root.mkdir()
    system_root = tmp_path / "system-skills"
    system_root.mkdir()

    roots = collect_skill_roots(
        cwd=cwd,
        project_skill_dirs=[repo_root_skills],
        user_root=user_root,
        system_root=system_root,
    )

    assert [root.scope for root in roots] == ["repo", "repo", "user", "system"]
    assert [root.path for root in roots] == [
        repo_root_skills.resolve(),
        repo_nested_skills.resolve(),
        user_root.resolve(),
        system_root.resolve(),
    ]


def test_discover_skills_cross_scope_name_conflict_prefers_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    repo_root = repo / ".agents" / "skills" / "repo-skill"
    _write_skill(repo_root, name="shared-skill", description="repo")

    user_root = tmp_path / "user-skills"
    _write_skill(user_root / "user-skill", name="shared-skill", description="user")

    result = discover_skills(cwd=repo, user_root=user_root, system_root=tmp_path / "none")

    assert len(result.skills) == 1
    assert result.skills[0].scope == "repo"
    assert result.skills[0].description == "repo"
    assert result.ambiguous_names == frozenset()


def test_discover_skills_same_scope_duplicate_marks_ambiguous(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cwd = repo / "pkg"
    cwd.mkdir(parents=True)
    (repo / ".git").mkdir()

    _write_skill(repo / ".agents" / "skills" / "first", name="duplicate", description="root")
    _write_skill(cwd / ".agents" / "skills" / "second", name="duplicate", description="nested")

    result = discover_skills(cwd=cwd, user_root=tmp_path / "none", system_root=tmp_path / "none")

    assert [skill.name for skill in result.skills] == ["duplicate"]
    assert result.skills[0].description == "root"
    assert result.ambiguous_names == frozenset({"duplicate"})


def test_discover_skills_honors_depth_limit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    deep = repo / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (repo / ".git").mkdir()

    _write_skill(repo / ".agents" / "skills" / "near", name="near", description="near")
    _write_skill(
        repo / ".agents" / "skills" / "x" / "y" / "z" / "far",
        name="far",
        description="far",
    )

    result = discover_skills(
        cwd=deep,
        user_root=tmp_path / "none",
        system_root=tmp_path / "none",
        max_depth=2,
    )

    assert [skill.name for skill in result.skills] == ["near"]


def _write_skill(skill_dir: Path, *, name: str, description: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "body",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
