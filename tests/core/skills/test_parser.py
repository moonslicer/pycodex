from __future__ import annotations

from pathlib import Path

import pytest
from pycodex.core.skills.models import SkillEnvVarDependency
from pycodex.core.skills.parser import SkillParseError, parse_sidecar_metadata, parse_skill_markdown


def test_parse_skill_markdown_with_required_fields_and_body(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        "\n".join(
            [
                "---",
                "name: db-migrate",
                "description: Generate SQL migrations with rollback checks.",
                "metadata:",
                "  short-description: Safe migration workflow",
                "---",
                "When invoked:",
                "1. Inspect schema and constraints.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_skill_markdown(skill_file)

    assert parsed.name == "db-migrate"
    assert parsed.description == "Generate SQL migrations with rollback checks."
    assert parsed.short_description == "Safe migration workflow"
    assert parsed.body == "When invoked:\n1. Inspect schema and constraints.\n"


def test_parse_skill_markdown_requires_frontmatter(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("No frontmatter\n", encoding="utf-8")

    with pytest.raises(SkillParseError, match="must start with YAML frontmatter delimiter"):
        parse_skill_markdown(skill_file)


def test_parse_skill_markdown_requires_description(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        "\n".join(
            [
                "---",
                "name: db-migrate",
                "---",
                "Body",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillParseError, match="missing required frontmatter field: description"):
        parse_skill_markdown(skill_file)


def test_parse_skill_markdown_rejects_non_mapping_metadata(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        "\n".join(
            [
                "---",
                "name: lint-fix",
                "description: Run lint fix and tests.",
                "metadata: text",
                "---",
                "Body",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillParseError, match="metadata must be a mapping"):
        parse_skill_markdown(skill_file)


def test_parse_sidecar_metadata_parses_env_var_dependencies_and_policy(tmp_path: Path) -> None:
    sidecar_file = tmp_path / "openai.yaml"
    sidecar_file.write_text(
        "\n".join(
            [
                "dependencies:",
                "  - type: env_var",
                "    name: OPENAI_API_KEY",
                "  - type: env_var",
                "    name: DATABASE_URL",
                "  - type: mcp",
                "    name: github",
                "policy:",
                "  allow_implicit_invocation: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_sidecar_metadata(sidecar_file)

    assert parsed.allow_implicit_invocation is True
    assert parsed.dependencies is not None
    assert parsed.dependencies.env_vars == (
        SkillEnvVarDependency(name="OPENAI_API_KEY"),
        SkillEnvVarDependency(name="DATABASE_URL"),
    )
    assert parsed.warnings == ()


def test_parse_sidecar_metadata_supports_mapping_env_vars_shape(tmp_path: Path) -> None:
    sidecar_file = tmp_path / "openai.yaml"
    sidecar_file.write_text(
        "\n".join(
            [
                "dependencies:",
                "  env_vars:",
                "    - OPENAI_API_KEY",
                "    - name: DATABASE_URL",
                "    - OPENAI_API_KEY",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_sidecar_metadata(sidecar_file)

    assert parsed.dependencies is not None
    assert parsed.dependencies.env_vars == (
        SkillEnvVarDependency(name="OPENAI_API_KEY"),
        SkillEnvVarDependency(name="DATABASE_URL"),
    )


def test_parse_sidecar_metadata_returns_warning_for_malformed_yaml(tmp_path: Path) -> None:
    sidecar_file = tmp_path / "openai.yaml"
    sidecar_file.write_text("dependencies:\n\t- type: env_var\n", encoding="utf-8")

    parsed = parse_sidecar_metadata(sidecar_file)

    assert parsed.dependencies is None
    assert parsed.allow_implicit_invocation is False
    assert len(parsed.warnings) == 1
    assert "failed to parse sidecar metadata" in parsed.warnings[0]


def test_parse_sidecar_metadata_returns_warning_for_invalid_shape(tmp_path: Path) -> None:
    sidecar_file = tmp_path / "openai.yaml"
    sidecar_file.write_text(
        "\n".join(
            [
                "dependencies: invalid",
                "policy:",
                "  allow_implicit_invocation: yes",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_sidecar_metadata(sidecar_file)

    assert parsed.dependencies is None
    assert parsed.allow_implicit_invocation is False
    assert parsed.warnings == (
        "ignored dependencies because it is not a list or mapping",
        "ignored policy.allow_implicit_invocation because it is not a boolean",
    )


def test_parse_sidecar_metadata_missing_file_is_noop(tmp_path: Path) -> None:
    parsed = parse_sidecar_metadata(tmp_path / "missing.yaml")

    assert parsed.dependencies is None
    assert parsed.allow_implicit_invocation is False
    assert parsed.warnings == ()
