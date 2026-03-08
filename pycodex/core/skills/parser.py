"""Skill markdown and sidecar parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from pycodex.core.skills.models import SkillDependencies, SkillEnvVarDependency

YamlScalar: TypeAlias = str | int | float | bool | None
YamlValue: TypeAlias = YamlScalar | dict[str, "YamlValue"] | list["YamlValue"]

_INT_RE = re.compile(r"^-?[0-9]+$")
_FLOAT_RE = re.compile(r"^-?(?:[0-9]+\.[0-9]*|\.[0-9]+)$")


@dataclass(frozen=True, slots=True)
class SkillParseError(ValueError):
    """Raised when required skill parsing fails."""

    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True, slots=True)
class ParsedSkillDocument:
    """Validated `SKILL.md` data needed for registration."""

    name: str
    description: str
    short_description: str | None
    body: str
    dependencies: SkillDependencies | None = None
    warnings: tuple[str, ...] = ()


def parse_skill_markdown(skill_path: Path) -> ParsedSkillDocument:
    """Parse and validate a `SKILL.md` file."""
    text = _read_text(skill_path)
    frontmatter_text, body = _extract_frontmatter(text, path=skill_path)
    parsed = _parse_yaml(frontmatter_text, path=skill_path)
    if not isinstance(parsed, dict):
        raise SkillParseError(skill_path, "frontmatter must be a mapping")

    name = _required_string(parsed, "name", path=skill_path)
    description = _required_string(parsed, "description", path=skill_path)

    short_description: str | None = None
    metadata = parsed.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise SkillParseError(skill_path, "metadata must be a mapping when present")
        raw_short = metadata.get("short-description")
        if raw_short is not None:
            short_description = _line_string(
                raw_short,
                field_name="metadata.short-description",
                path=skill_path,
            )

    dep_warnings: list[str] = []
    dependencies = _extract_dependencies(parsed.get("dependencies"), warnings=dep_warnings)
    return ParsedSkillDocument(
        name=name,
        description=description,
        short_description=short_description,
        body=body,
        dependencies=dependencies,
        warnings=tuple(dep_warnings),
    )



def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillParseError(path, f"failed to read file: {exc}") from exc


def _extract_frontmatter(text: str, *, path: Path) -> tuple[str, str]:
    if text.startswith("\ufeff"):
        text = text[1:]

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SkillParseError(path, "SKILL.md must start with YAML frontmatter delimiter '---'")

    closing_index: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        raise SkillParseError(path, "frontmatter is missing closing '---' delimiter")

    frontmatter_text = "".join(lines[1:closing_index])
    body = "".join(lines[closing_index + 1 :])
    return frontmatter_text, body


def _required_string(parsed: dict[str, YamlValue], key: str, *, path: Path) -> str:
    raw = parsed.get(key)
    if raw is None:
        raise SkillParseError(path, f"missing required frontmatter field: {key}")
    return _line_string(raw, field_name=key, path=path)


def _line_string(raw: YamlValue, *, field_name: str, path: Path) -> str:
    if not isinstance(raw, str):
        raise SkillParseError(path, f"{field_name} must be a string")
    value = raw.strip()
    if not value:
        raise SkillParseError(path, f"{field_name} must not be empty")
    if "\n" in value or "\r" in value:
        raise SkillParseError(path, f"{field_name} must be single-line")
    return value


def _extract_dependencies(
    raw_dependencies: YamlValue | None,
    *,
    warnings: list[str],
) -> SkillDependencies | None:
    if raw_dependencies is None:
        return None

    names: list[str] = []
    if isinstance(raw_dependencies, list):
        for index, item in enumerate(raw_dependencies):
            if not isinstance(item, dict):
                warnings.append(f"ignored dependencies[{index}] because it is not a mapping")
                continue
            item_type = item.get("type")
            name = item.get("name")
            if item_type != "env_var":
                continue
            if not isinstance(name, str) or not name.strip():
                warnings.append(f"ignored dependencies[{index}] because env_var.name is missing")
                continue
            names.append(name.strip())
    elif isinstance(raw_dependencies, dict):
        env_vars = raw_dependencies.get("env_vars")
        if env_vars is None:
            warnings.append("ignored dependencies mapping because env_vars is missing")
        elif not isinstance(env_vars, list):
            warnings.append("ignored dependencies.env_vars because it is not a list")
        else:
            for index, env_var in enumerate(env_vars):
                if isinstance(env_var, str):
                    if env_var.strip():
                        names.append(env_var.strip())
                    else:
                        warnings.append(
                            f"ignored dependencies.env_vars[{index}] because it is empty"
                        )
                    continue
                if isinstance(env_var, dict):
                    name = env_var.get("name")
                    if isinstance(name, str) and name.strip():
                        names.append(name.strip())
                    else:
                        warnings.append(
                            f"ignored dependencies.env_vars[{index}] because name is missing"
                        )
                    continue
                warnings.append(f"ignored dependencies.env_vars[{index}] because it is invalid")
    else:
        warnings.append("ignored dependencies because it is not a list or mapping")

    deduped_names = tuple(dict.fromkeys(names))
    if not deduped_names:
        return None
    return SkillDependencies(
        env_vars=tuple(SkillEnvVarDependency(name=name) for name in deduped_names),
    )



def _parse_yaml(text: str, *, path: Path) -> YamlValue:
    lines = text.splitlines()
    index = _skip_ignored_lines(lines, 0)
    if index >= len(lines):
        return {}

    value, next_index = _parse_block(lines, index=index, indent=0, path=path)
    tail_index = _skip_ignored_lines(lines, next_index)
    if tail_index != len(lines):
        raise SkillParseError(path, f"unexpected trailing content at line {tail_index + 1}")
    return value


def _parse_block(
    lines: list[str],
    *,
    index: int,
    indent: int,
    path: Path,
) -> tuple[YamlValue, int]:
    if index >= len(lines):
        raise SkillParseError(path, "unexpected end of YAML content")

    line = lines[index]
    line_indent = _leading_spaces(line, path=path, line_no=index + 1)
    if line_indent != indent:
        raise SkillParseError(path, f"invalid indentation at line {index + 1}")

    stripped = line.strip()
    if stripped.startswith("- "):
        return _parse_sequence(lines, index=index, indent=indent, path=path)
    return _parse_mapping(lines, index=index, indent=indent, path=path)


def _parse_mapping(
    lines: list[str],
    *,
    index: int,
    indent: int,
    path: Path,
) -> tuple[dict[str, YamlValue], int]:
    mapping: dict[str, YamlValue] = {}

    while index < len(lines):
        if _is_ignored_line(lines[index]):
            index += 1
            continue

        line = lines[index]
        line_indent = _leading_spaces(line, path=path, line_no=index + 1)
        if line_indent < indent:
            break
        if line_indent > indent:
            raise SkillParseError(path, f"invalid indentation at line {index + 1}")

        stripped = line[line_indent:].strip()
        if stripped.startswith("- "):
            raise SkillParseError(path, f"sequence item not allowed at line {index + 1}")

        key, value_text = _split_mapping_entry(stripped, path=path, line_no=index + 1)
        index += 1

        if value_text is None:
            nested_start = _skip_ignored_lines(lines, index)
            if nested_start < len(lines):
                nested_indent = _leading_spaces(
                    lines[nested_start], path=path, line_no=nested_start + 1
                )
                if nested_indent > indent:
                    nested, index = _parse_block(
                        lines,
                        index=nested_start,
                        indent=indent + 2,
                        path=path,
                    )
                    mapping[key] = nested
                    continue
            mapping[key] = {}
            index = nested_start
            continue

        mapping[key] = _parse_scalar(value_text)
        index = _skip_ignored_lines(lines, index)

    return mapping, index


def _parse_sequence(
    lines: list[str],
    *,
    index: int,
    indent: int,
    path: Path,
) -> tuple[list[YamlValue], int]:
    sequence: list[YamlValue] = []

    while index < len(lines):
        if _is_ignored_line(lines[index]):
            index += 1
            continue

        line = lines[index]
        line_indent = _leading_spaces(line, path=path, line_no=index + 1)
        if line_indent < indent:
            break
        if line_indent > indent:
            raise SkillParseError(path, f"invalid indentation at line {index + 1}")

        stripped = line[line_indent:].strip()
        if not stripped.startswith("- "):
            break

        item_text = stripped[2:].strip()
        index += 1

        if not item_text:
            nested_start = _skip_ignored_lines(lines, index)
            if nested_start >= len(lines):
                raise SkillParseError(path, f"missing value for sequence item at line {index}")
            nested_indent = _leading_spaces(
                lines[nested_start], path=path, line_no=nested_start + 1
            )
            if nested_indent <= indent:
                raise SkillParseError(
                    path, f"missing nested block for sequence item at line {index}"
                )
            nested, index = _parse_block(lines, index=nested_start, indent=indent + 2, path=path)
            sequence.append(nested)
            continue

        if _looks_like_mapping_entry(item_text):
            key, value_text = _split_mapping_entry(item_text, path=path, line_no=index)
            item_mapping: dict[str, YamlValue] = {}
            if value_text is None:
                nested_start = _skip_ignored_lines(lines, index)
                if nested_start < len(lines):
                    nested_indent = _leading_spaces(
                        lines[nested_start],
                        path=path,
                        line_no=nested_start + 1,
                    )
                    if nested_indent > indent:
                        nested, index = _parse_block(
                            lines,
                            index=nested_start,
                            indent=indent + 2,
                            path=path,
                        )
                        item_mapping[key] = nested
                    else:
                        item_mapping[key] = {}
                        index = nested_start
                else:
                    item_mapping[key] = {}
            else:
                item_mapping[key] = _parse_scalar(value_text)

            index = _consume_inline_mapping_tail(
                lines,
                index=index,
                indent=indent,
                item_mapping=item_mapping,
                path=path,
            )
            sequence.append(item_mapping)
            continue

        sequence.append(_parse_scalar(item_text))
        index = _skip_ignored_lines(lines, index)

    return sequence, index


def _consume_inline_mapping_tail(
    lines: list[str],
    *,
    index: int,
    indent: int,
    item_mapping: dict[str, YamlValue],
    path: Path,
) -> int:
    while True:
        next_index = _skip_ignored_lines(lines, index)
        if next_index >= len(lines):
            return next_index

        next_line = lines[next_index]
        next_indent = _leading_spaces(next_line, path=path, line_no=next_index + 1)
        if next_indent <= indent:
            return next_index
        if next_indent != indent + 2:
            raise SkillParseError(path, f"invalid indentation at line {next_index + 1}")

        stripped = next_line[next_indent:].strip()
        if stripped.startswith("- "):
            raise SkillParseError(path, f"unexpected nested sequence at line {next_index + 1}")

        key, value_text = _split_mapping_entry(stripped, path=path, line_no=next_index + 1)
        index = next_index + 1
        if value_text is None:
            nested_start = _skip_ignored_lines(lines, index)
            if nested_start < len(lines):
                nested_indent = _leading_spaces(
                    lines[nested_start], path=path, line_no=nested_start + 1
                )
                if nested_indent > next_indent:
                    nested, index = _parse_block(
                        lines,
                        index=nested_start,
                        indent=next_indent + 2,
                        path=path,
                    )
                    item_mapping[key] = nested
                    continue
            item_mapping[key] = {}
            index = nested_start
            continue

        item_mapping[key] = _parse_scalar(value_text)


def _split_mapping_entry(line: str, *, path: Path, line_no: int) -> tuple[str, str | None]:
    if ":" not in line:
        raise SkillParseError(path, f"expected key:value mapping at line {line_no}")

    key_raw, value_raw = line.split(":", 1)
    key = key_raw.strip()
    if not key:
        raise SkillParseError(path, f"missing key in mapping at line {line_no}")

    if not value_raw.strip():
        return key, None
    return key, value_raw.strip()


def _looks_like_mapping_entry(value: str) -> bool:
    if ":" not in value:
        return False
    key = value.split(":", 1)[0].strip()
    if not key:
        return False
    return all(char.isalnum() or char in {"_", "-", "."} for char in key)


def _parse_scalar(value: str) -> YamlScalar:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "~"}:
        return None
    if _INT_RE.match(value):
        return int(value)
    if _FLOAT_RE.match(value):
        return float(value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _leading_spaces(line: str, *, path: Path, line_no: int) -> int:
    if "\t" in line:
        raise SkillParseError(path, f"tabs are not supported in YAML at line {line_no}")
    return len(line) - len(line.lstrip(" "))


def _is_ignored_line(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _skip_ignored_lines(lines: list[str], index: int) -> int:
    current = index
    while current < len(lines) and _is_ignored_line(lines[current]):
        current += 1
    return current
