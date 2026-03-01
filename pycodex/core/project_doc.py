"""Hierarchical project instruction document loading."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

PROJECT_DOC_SEPARATOR = "\n--- project-doc ---\n"
_TRUNCATED_MARKER = "\n[truncated]"


def find_git_root(start: Path) -> Path | None:
    """Walk upward from start to discover the nearest directory containing .git."""
    current = start.resolve()
    if current.is_file():
        current = current.parent

    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def load_project_instructions(
    cwd: Path,
    filenames: Sequence[str] = ("AGENTS.md",),
    max_bytes: int = 32_768,
) -> str | None:
    """Load project instruction docs from repo root down to cwd."""
    if max_bytes <= 0:
        return None

    root = find_git_root(cwd) or cwd.resolve()
    search_dirs = _directories_from_root_to_cwd(root=root, cwd=cwd.resolve())

    parts: list[str] = []
    for directory in search_dirs:
        for filename in filenames:
            candidate = directory / filename
            if not candidate.is_file():
                continue
            try:
                parts.append(candidate.read_text(encoding="utf-8"))
            except OSError:
                continue

    if not parts:
        return None

    combined = PROJECT_DOC_SEPARATOR.join(parts)
    return _truncate_utf8(combined, max_bytes=max_bytes)


def _directories_from_root_to_cwd(*, root: Path, cwd: Path) -> list[Path]:
    if root == cwd:
        return [root]

    relative = cwd.relative_to(root)
    directories = [root]
    current = root
    for part in relative.parts:
        current = current / part
        directories.append(current)
    return directories


def _truncate_utf8(text: str, *, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    marker_bytes = _TRUNCATED_MARKER.encode("utf-8")
    if max_bytes <= len(marker_bytes):
        truncated = encoded[:max_bytes]
        while True:
            try:
                return truncated.decode("utf-8")
            except UnicodeDecodeError:
                if len(truncated) == 0:
                    return ""
                truncated = truncated[:-1]

    keep_len = max_bytes - len(marker_bytes)
    truncated = encoded[:keep_len]
    while True:
        try:
            prefix = truncated.decode("utf-8")
            break
        except UnicodeDecodeError:
            if len(truncated) == 0:
                prefix = ""
                break
            truncated = truncated[:-1]

    return prefix + _TRUNCATED_MARKER
