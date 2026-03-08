"""Skills registry cache and indexes."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from pycodex.core.skills.discovery import SkillDiscoveryResult, discover_skills
from pycodex.core.skills.models import SkillMetadata


@dataclass(frozen=True, slots=True)
class SkillRegistry:
    """Resolved skill registry with deterministic lookup indexes."""

    skills: tuple[SkillMetadata, ...]
    errors: tuple[str, ...]
    ambiguous_names: frozenset[str]
    by_name: Mapping[str, SkillMetadata]
    by_path: Mapping[Path, SkillMetadata]

    def is_model_invocation_disabled(self, name: str) -> bool:
        """Return whether the named skill opts out of model self-invocation."""
        skill = self.by_name.get(name)
        if skill is None:
            return False
        return skill.disable_model_invocation


DiscoverFn = Callable[..., SkillDiscoveryResult]


class SkillsManager:
    """Cache and return skill registries keyed by cwd/config fingerprint."""

    def __init__(self, *, discover_fn: DiscoverFn = discover_skills) -> None:
        self._discover_fn: DiscoverFn = discover_fn
        self._cache: dict[tuple[Path, str], SkillRegistry] = {}

    def get_registry(
        self,
        *,
        cwd: Path,
        config_fingerprint: str = "",
        project_skill_dirs: Iterable[Path | str] = (),
        user_root: Path | None = None,
        system_root: Path | None = None,
        force_reload: bool = False,
    ) -> SkillRegistry:
        """Return a cached or freshly loaded registry for `cwd`."""
        resolved_cwd = cwd.resolve()
        cache_key = (resolved_cwd, config_fingerprint)

        if not force_reload and cache_key in self._cache:
            return self._cache[cache_key]

        discovery = self._discover_fn(
            cwd=resolved_cwd,
            project_skill_dirs=tuple(project_skill_dirs),
            user_root=user_root,
            system_root=system_root,
        )
        registry = _build_registry(discovery)
        self._cache[cache_key] = registry
        return registry

    def clear_cache(self, *, cwd: Path | None = None) -> None:
        """Clear the full cache or entries for one cwd."""
        if cwd is None:
            self._cache.clear()
            return

        resolved_cwd = cwd.resolve()
        keys_to_delete = [key for key in self._cache if key[0] == resolved_cwd]
        for key in keys_to_delete:
            del self._cache[key]


def _build_registry(discovery: SkillDiscoveryResult) -> SkillRegistry:
    by_name: dict[str, SkillMetadata] = {}
    by_path: dict[Path, SkillMetadata] = {}

    for skill in discovery.skills:
        by_path[skill.path_to_skill_md] = skill
        if skill.name in discovery.ambiguous_names:
            continue
        by_name[skill.name] = skill

    return SkillRegistry(
        skills=discovery.skills,
        errors=discovery.errors,
        ambiguous_names=discovery.ambiguous_names,
        by_name=MappingProxyType(by_name),
        by_path=MappingProxyType(by_path),
    )
