"""Explicit skill mention extraction and resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pycodex.core.skills.manager import SkillRegistry
from pycodex.core.skills.models import SkillMetadata

_PLAIN_MENTION_RE = re.compile(r"\$([a-zA-Z0-9][a-zA-Z0-9_-]*)")
_FENCE_MARKERS = ("```", "~~~")


@dataclass(frozen=True, slots=True)
class SkillMention:
    """Candidate mention parsed from user text."""

    name: str


@dataclass(frozen=True, slots=True)
class UnresolvedSkillMention:
    """Candidate mention that could not be resolved."""

    mention: SkillMention
    reason: Literal["not_found", "ambiguous"]


@dataclass(frozen=True, slots=True)
class SkillResolutionResult:
    """Resolved skills in injection order and deterministic unresolved mentions."""

    resolved: tuple[SkillMetadata, ...]
    unresolved: tuple[UnresolvedSkillMention, ...]


def extract_skill_mentions(text: str) -> tuple[SkillMention, ...]:
    """Extract $name mention candidates, skipping code blocks and inline code."""
    masked_ranges = _masked_code_ranges(text)
    mentions: list[SkillMention] = []
    seen_names: set[str] = set()

    for match in _PLAIN_MENTION_RE.finditer(text):
        if _overlaps_masked_range(match.start(), match.end(), masked_ranges):
            continue
        name = match.group(1)
        if name in seen_names:
            continue
        seen_names.add(name)
        mentions.append(SkillMention(name=name))

    return tuple(mentions)


def resolve_skill_mentions(text: str, registry: SkillRegistry) -> SkillResolutionResult:
    """Resolve extracted mentions against registry indexes."""
    mentions = extract_skill_mentions(text)
    resolved: list[SkillMetadata] = []
    unresolved: list[UnresolvedSkillMention] = []
    seen_skill_paths: set[Path] = set()

    for mention in mentions:
        if mention.name in registry.ambiguous_names:
            unresolved.append(UnresolvedSkillMention(mention=mention, reason="ambiguous"))
            continue

        skill = registry.by_name.get(mention.name)
        if skill is None:
            unresolved.append(UnresolvedSkillMention(mention=mention, reason="not_found"))
            continue
        if skill.path_to_skill_md in seen_skill_paths:
            continue
        seen_skill_paths.add(skill.path_to_skill_md)
        resolved.append(skill)

    return SkillResolutionResult(
        resolved=tuple(resolved),
        unresolved=tuple(unresolved),
    )


def _masked_code_ranges(text: str) -> list[tuple[int, int]]:
    ranges = _fenced_code_ranges(text)
    inline_ranges = _inline_code_ranges(text, existing_ranges=ranges)
    all_ranges = ranges + inline_ranges
    return _merge_ranges(all_ranges)


def _fenced_code_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        marker = _fence_marker_at(text, index)
        if marker is None:
            index += 1
            continue

        end = text.find(marker, index + len(marker))
        if end == -1:
            ranges.append((index, len(text)))
            break

        ranges.append((index, end + len(marker)))
        index = end + len(marker)
    return ranges


def _inline_code_ranges(
    text: str, *, existing_ranges: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if text[index] != "`" or _position_in_ranges(index, existing_ranges):
            index += 1
            continue
        end = text.find("`", index + 1)
        if end == -1:
            break
        ranges.append((index, end + 1))
        index = end + 1
    return ranges


def _fence_marker_at(text: str, index: int) -> str | None:
    for marker in _FENCE_MARKERS:
        if text.startswith(marker, index):
            return marker
    return None


def _overlaps_masked_range(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start < masked_end and end > masked_start for masked_start, masked_end in ranges)


def _position_in_ranges(index: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in ranges)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged: list[tuple[int, int]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
            continue
        merged.append((start, end))
    return merged
