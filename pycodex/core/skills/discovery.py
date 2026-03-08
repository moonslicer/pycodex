"""Skill root discovery and metadata loading."""

from __future__ import annotations

import logging
import os
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pycodex.core.project_doc import find_git_root
from pycodex.core.skills.models import SkillMetadata, SkillScope
from pycodex.core.skills.parser import SkillParseError, parse_skill_markdown

_DEFAULT_MAX_DEPTH = 8
_DEFAULT_MAX_DIRECTORIES = 2_000
_log = logging.getLogger("pycodex.skills.discovery")


@dataclass(frozen=True, slots=True)
class SkillRoot:
    """Canonical skill root path and resolved scope."""

    path: Path
    scope: SkillScope


@dataclass(frozen=True, slots=True)
class SkillDiscoveryResult:
    """Loaded skills and deterministic diagnostics."""

    skills: tuple[SkillMetadata, ...]
    errors: tuple[str, ...]
    ambiguous_names: frozenset[str]


def collect_skill_roots(
    *,
    cwd: Path,
    project_skill_dirs: Iterable[Path | str] = (),
    user_root: Path | None = None,
    system_root: Path | None = None,
) -> tuple[SkillRoot, ...]:
    """Collect existing skill roots in deterministic precedence order."""
    resolved_cwd = cwd.resolve()
    repo_root = find_git_root(resolved_cwd)

    roots: list[SkillRoot] = []

    if repo_root is not None:
        for ancestor in _directories_from_root_to_cwd(root=repo_root, cwd=resolved_cwd):
            candidate = ancestor / ".agents" / "skills"
            if candidate.is_dir():
                roots.append(SkillRoot(path=candidate.resolve(), scope="repo"))

    project_base = repo_root if repo_root is not None else resolved_cwd
    for configured in project_skill_dirs:
        raw = Path(configured)
        candidate = raw if raw.is_absolute() else (project_base / raw)
        if candidate.is_dir():
            roots.append(SkillRoot(path=candidate.resolve(), scope="repo"))

    effective_user_root = user_root or (Path.home() / ".agents" / "skills")
    if effective_user_root.is_dir():
        roots.append(SkillRoot(path=effective_user_root.resolve(), scope="user"))

    default_system_root = Path(os.getenv("PYCODEX_HOME", str(Path.home() / ".pycodex")))
    effective_system_root = system_root or (default_system_root / "skills" / ".system")
    if effective_system_root.is_dir():
        roots.append(SkillRoot(path=effective_system_root.resolve(), scope="system"))

    deduped: list[SkillRoot] = []
    seen_paths: set[Path] = set()
    for root in roots:
        if root.path in seen_paths:
            continue
        deduped.append(root)
        seen_paths.add(root.path)
    return tuple(deduped)


def discover_skills(
    *,
    cwd: Path,
    project_skill_dirs: Iterable[Path | str] = (),
    user_root: Path | None = None,
    system_root: Path | None = None,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    max_directories: int = _DEFAULT_MAX_DIRECTORIES,
) -> SkillDiscoveryResult:
    """Load skills from discovered roots with deterministic conflict handling."""
    roots = collect_skill_roots(
        cwd=cwd,
        project_skill_dirs=project_skill_dirs,
        user_root=user_root,
        system_root=system_root,
    )

    errors: list[str] = []
    skills: list[SkillMetadata] = []
    ambiguous_names: set[str] = set()

    seen_skill_paths: set[Path] = set()
    kept_by_name: dict[str, SkillMetadata] = {}

    for root in roots:
        skill_paths = _scan_skill_files(
            root.path,
            max_depth=max_depth,
            max_directories=max_directories,
            errors=errors,
        )
        for skill_path in skill_paths:
            canonical_skill_path = skill_path.resolve()
            if canonical_skill_path in seen_skill_paths:
                errors.append(f"duplicate skill path skipped: {canonical_skill_path}")
                _log.debug(
                    "skill.dedup_skipped name=unknown scope=%s skipped_path=%s",
                    root.scope,
                    canonical_skill_path,
                )
                continue
            seen_skill_paths.add(canonical_skill_path)

            try:
                parsed_skill = parse_skill_markdown(canonical_skill_path)
            except SkillParseError as exc:
                errors.append(str(exc))
                _log.warning(
                    "skill.load_error path=%s reason=%s", canonical_skill_path, exc.message
                )
                continue

            for warning in parsed_skill.warnings:
                errors.append(f"{canonical_skill_path}: {warning}")
                _log.warning("skill.load_warning path=%s reason=%s", canonical_skill_path, warning)

            metadata = SkillMetadata(
                name=parsed_skill.name,
                description=parsed_skill.description,
                short_description=parsed_skill.short_description,
                path_to_skill_md=canonical_skill_path,
                skill_root=canonical_skill_path.parent,
                scope=root.scope,
                dependencies=parsed_skill.dependencies,
            )

            existing = kept_by_name.get(metadata.name)
            if existing is None:
                kept_by_name[metadata.name] = metadata
                skills.append(metadata)
                _log.debug(
                    "skill.loaded name=%s scope=%s path=%s",
                    metadata.name,
                    metadata.scope,
                    metadata.path_to_skill_md,
                )
                continue

            if existing.scope == metadata.scope:
                ambiguous_names.add(metadata.name)
                errors.append(
                    f"duplicate skill name in scope '{metadata.scope}' skipped: "
                    f"{metadata.name} ({metadata.path_to_skill_md})"
                )
                _log.debug(
                    "skill.dedup_skipped name=%s scope=%s kept_path=%s skipped_path=%s",
                    metadata.name,
                    metadata.scope,
                    existing.path_to_skill_md,
                    metadata.path_to_skill_md,
                )
                continue

            errors.append(
                "skill name shadowed by higher-precedence scope: "
                f"{metadata.name} ({metadata.scope} -> {existing.scope})"
            )
            _log.debug(
                "skill.dedup_skipped name=%s scope=%s kept_path=%s skipped_path=%s",
                metadata.name,
                metadata.scope,
                existing.path_to_skill_md,
                metadata.path_to_skill_md,
            )

    return SkillDiscoveryResult(
        skills=tuple(skills),
        errors=tuple(errors),
        ambiguous_names=frozenset(ambiguous_names),
    )


def _scan_skill_files(
    root: Path,
    *,
    max_depth: int,
    max_directories: int,
    errors: list[str],
) -> list[Path]:
    queue: deque[tuple[Path, int]] = deque([(root, 0)])
    root_resolved = root.resolve()
    visited: set[Path] = set()
    discovered: list[Path] = []
    scanned_directories = 0

    while queue:
        current, depth = queue.popleft()
        resolved_current = current.resolve()
        if not _is_path_within(resolved_current, root_resolved):
            errors.append(f"skipped path outside allowed root: {resolved_current}")
            continue
        if resolved_current in visited:
            continue
        visited.add(resolved_current)

        scanned_directories += 1
        if scanned_directories > max_directories:
            errors.append(f"directory scan limit reached under root: {root}")
            break

        skill_file = current / "SKILL.md"
        if skill_file.is_file():
            discovered.append(skill_file)

        if depth >= max_depth:
            continue

        try:
            children = sorted(
                (child for child in current.iterdir() if child.is_dir()),
                key=lambda path: path.name,
            )
        except OSError as exc:
            errors.append(f"failed to read directory {current}: {exc}")
            continue

        for child in children:
            resolved_child = child.resolve()
            if not _is_path_within(resolved_child, root_resolved):
                errors.append(f"skipped path outside allowed root: {resolved_child}")
                continue
            queue.append((child, depth + 1))

    return discovered


def _directories_from_root_to_cwd(*, root: Path, cwd: Path) -> list[Path]:
    if root == cwd:
        return [root]

    try:
        relative = cwd.relative_to(root)
    except ValueError:
        return [root]

    result = [root]
    current = root
    for part in relative.parts:
        current = current / part
        result.append(current)
    return result


def _is_path_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False
