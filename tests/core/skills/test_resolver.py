from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from pycodex.core.skills.manager import SkillRegistry
from pycodex.core.skills.models import SkillMetadata
from pycodex.core.skills.resolver import extract_skill_mentions, resolve_skill_mentions


def test_extract_skill_mentions_skips_fenced_and_inline_code() -> None:
    text = (
        "Use $alpha and $beta.\n"
        "Ignore `$inline` and ```\n$blocked\n``` plus $gamma."
    )

    mentions = extract_skill_mentions(text)

    assert [mention.name for mention in mentions] == ["alpha", "beta", "gamma"]


def test_resolve_skill_mentions_dedupes_duplicate_plain_mentions(tmp_path: Path) -> None:
    alpha = _skill(tmp_path / "alpha" / "SKILL.md", name="alpha")
    registry = _registry(skills=(alpha,))

    result = resolve_skill_mentions("run $alpha then $alpha again", registry)

    assert [skill.name for skill in result.resolved] == ["alpha"]
    assert result.unresolved == ()


def test_resolve_skill_mentions_marks_ambiguous_names(tmp_path: Path) -> None:
    duplicate = _skill(tmp_path / "duplicate" / "SKILL.md", name="duplicate")
    registry = _registry(skills=(duplicate,), ambiguous_names=frozenset({"duplicate"}))

    result = resolve_skill_mentions("try $duplicate", registry)

    assert result.resolved == ()
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason == "ambiguous"
    assert result.unresolved[0].mention.name == "duplicate"


def test_resolve_skill_mentions_reports_not_found_for_unknown_name(tmp_path: Path) -> None:
    known = _skill(tmp_path / "known" / "SKILL.md", name="known")
    registry = _registry(skills=(known,))

    result = resolve_skill_mentions("$unknown and $known", registry)

    assert [skill.name for skill in result.resolved] == ["known"]
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason == "not_found"
    assert result.unresolved[0].mention.name == "unknown"


def _registry(
    *,
    skills: tuple[SkillMetadata, ...],
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


def _skill(path: Path, *, name: str) -> SkillMetadata:
    resolved = path.resolve()
    return SkillMetadata(
        name=name,
        description=f"{name} description",
        short_description=None,
        path_to_skill_md=resolved,
        skill_root=resolved.parent,
        scope="repo",
    )
