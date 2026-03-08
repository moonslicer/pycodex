from __future__ import annotations

from pathlib import Path

import pytest
from pycodex.core.skills.models import SkillEnvVarDependency
from pycodex.core.skills.parser import SkillParseError, parse_skill_markdown


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


def test_parse_skill_markdown_parses_env_var_dependencies(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        "\n".join(
            [
                "---",
                "name: db-migrate",
                "description: Generate SQL migrations.",
                "dependencies:",
                "  env_vars:",
                "    - DATABASE_URL",
                "    - name: API_KEY",
                "    - DATABASE_URL",
                "---",
                "body",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_skill_markdown(skill_file)

    assert parsed.dependencies is not None
    assert parsed.dependencies.env_vars == (
        SkillEnvVarDependency(name="DATABASE_URL"),
        SkillEnvVarDependency(name="API_KEY"),
    )
    assert parsed.warnings == ()


def test_parse_skill_markdown_warns_on_malformed_dependencies(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        "\n".join(["---", "name: foo", "description: Foo.", "dependencies: invalid", "---", "body"])
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_skill_markdown(skill_file)

    assert parsed.dependencies is None
    assert len(parsed.warnings) == 1
    assert "ignored dependencies" in parsed.warnings[0]


def test_parse_skill_markdown_parses_disable_model_invocation(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        "\n".join(
            [
                "---",
                "name: no-model",
                "description: Keep this skill user-invoked only.",
                "disable-model-invocation: true",
                "---",
                "body",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parsed = parse_skill_markdown(skill_file)

    assert parsed.disable_model_invocation is True


def test_parse_skill_markdown_rejects_non_boolean_disable_model_invocation(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        "\n".join(
            [
                "---",
                "name: invalid",
                "description: Invalid disable flag.",
                "disable-model-invocation: nope",
                "---",
                "body",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillParseError, match="disable-model-invocation must be a boolean"):
        parse_skill_markdown(skill_file)
