from __future__ import annotations

from pathlib import Path

from pycodex.approval.policy import ApprovalPolicy
from pycodex.approval.sandbox import SandboxPolicy
from pycodex.core.agent_profile import CODEX_PROFILE, AgentProfile
from pycodex.core.config import Config, load_config

_MISSING_GLOBAL_CONFIG = Path("does-not-exist-global.toml")


def test_config_defaults() -> None:
    config = Config()
    assert config.model == "gpt-4.1-mini"
    assert config.api_key is None
    assert config.api_base_url is None
    assert isinstance(config.cwd, Path)
    assert config.profile == CODEX_PROFILE
    assert config.project_doc_max_bytes == 32_768
    assert config.compaction_threshold_ratio == 0.2
    assert config.compaction_context_window_tokens == 128_000
    assert config.compaction_strategy == "threshold_v1"
    assert config.compaction_implementation == "model_summary_v1"
    assert config.compaction_custom_instructions == ""
    assert config.compaction_options == {}
    assert config.default_approval_policy == ApprovalPolicy.NEVER
    assert config.default_sandbox_policy == SandboxPolicy.DANGER_FULL_ACCESS


def test_load_config_missing_toml_uses_defaults_and_env(monkeypatch) -> None:
    monkeypatch.delenv("PYCODEX_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("PYCODEX_CWD", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    config = load_config(
        config_path=Path("does-not-exist.toml"),
        global_config_path=_MISSING_GLOBAL_CONFIG,
    )
    assert config.model == "gpt-4.1-mini"
    assert config.api_key == "test-key"  # pragma: allowlist secret


def test_load_config_precedence_defaults_then_toml_then_env(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "pycodex.toml"
    config_file.write_text(
        'model = "toml-model"\n'
        'api_key = "toml-key"\n'  # pragma: allowlist secret
        'api_base_url = "https://toml.example"\n'
        f'cwd = "{tmp_path}"\n',
        encoding="utf-8",
    )

    monkeypatch.setenv("PYCODEX_MODEL", "env-model")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example")

    config = load_config(config_path=config_file, global_config_path=_MISSING_GLOBAL_CONFIG)
    assert config.model == "env-model"
    assert config.api_key == "env-key"  # pragma: allowlist secret
    assert config.api_base_url == "https://env.example"
    assert config.cwd == tmp_path


def test_load_config_env_cwd_is_parsed_as_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PYCODEX_CWD", str(tmp_path))
    config = load_config(
        config_path=Path("does-not-exist.toml"),
        global_config_path=_MISSING_GLOBAL_CONFIG,
    )
    assert config.cwd == tmp_path


def test_load_config_profile_from_toml(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PYCODEX_INSTRUCTIONS", raising=False)
    config_file = tmp_path / "pycodex.toml"
    config_file.write_text(
        "\n".join(
            [
                'model = "toml-model"',
                "project_doc_max_bytes = 65535",
                "",
                "[profile]",
                'name = "support"',
                'instructions = "Support instructions."',
                'instruction_filenames = ["SUPPORT.md"]',
                'enabled_tools = ["read_file"]',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path=config_file, global_config_path=_MISSING_GLOBAL_CONFIG)

    assert config.model == "toml-model"
    assert config.project_doc_max_bytes == 65535
    assert config.profile == AgentProfile(
        name="support",
        instructions="Support instructions.",
        instruction_filenames=("SUPPORT.md",),
        enabled_tools=("read_file",),
    )


def test_load_config_env_instructions_overrides_profile_instructions(
    tmp_path: Path, monkeypatch
) -> None:
    config_file = tmp_path / "pycodex.toml"
    config_file.write_text(
        "\n".join(
            [
                "[profile]",
                'name = "support"',
                'instructions = "Support instructions."',
                'instruction_filenames = ["SUPPORT.md"]',
                'enabled_tools = ["read_file"]',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PYCODEX_INSTRUCTIONS", "Override instructions.")

    config = load_config(config_path=config_file, global_config_path=_MISSING_GLOBAL_CONFIG)

    assert config.profile.instructions == "Override instructions."
    assert config.profile.name == "support"
    assert config.profile.instruction_filenames == ("SUPPORT.md",)
    assert config.profile.enabled_tools == ("read_file",)


def test_load_config_global_config_applies_when_project_missing(tmp_path: Path) -> None:
    global_config = tmp_path / "global.toml"
    global_config.write_text(
        "\n".join(
            [
                'model = "global-model"',
                "compaction_threshold_ratio = 0.33",
                "compaction_context_window_tokens = 64000",
                'compaction_strategy = "threshold_v1"',
                'compaction_implementation = "local_summary_v1"',
                'compaction_custom_instructions = "Focus on code diffs."',
                'default_approval_policy = "on-request"',
                'default_sandbox_policy = "read-only"',
                "",
                "[compaction_options.strategy]",
                "keep_recent_items = 6",
                "",
                "[compaction_options.implementation]",
                "max_lines = 5",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(
        config_path=tmp_path / "missing-project.toml",
        global_config_path=global_config,
    )

    assert config.model == "global-model"
    assert config.compaction_threshold_ratio == 0.33
    assert config.compaction_context_window_tokens == 64000
    assert config.compaction_strategy == "threshold_v1"
    assert config.compaction_implementation == "local_summary_v1"
    assert config.compaction_custom_instructions == "Focus on code diffs."
    assert config.default_approval_policy == ApprovalPolicy.ON_REQUEST
    assert config.default_sandbox_policy == SandboxPolicy.READ_ONLY
    assert config.compaction_options == {
        "strategy": {"keep_recent_items": 6},
        "implementation": {"max_lines": 5},
    }


def test_load_config_reads_compaction_custom_instructions_from_env(monkeypatch) -> None:
    monkeypatch.setenv("PYCODEX_COMPACTION_CUSTOM_INSTRUCTIONS", "Summarize Python changes.")

    config = load_config(
        config_path=Path("does-not-exist.toml"),
        global_config_path=_MISSING_GLOBAL_CONFIG,
    )

    assert config.compaction_custom_instructions == "Summarize Python changes."


def test_load_config_precedence_env_over_project_over_global(tmp_path: Path, monkeypatch) -> None:
    global_config = tmp_path / "global.toml"
    global_config.write_text(
        "\n".join(
            [
                'model = "global-model"',
                'default_approval_policy = "on-request"',
                'default_sandbox_policy = "read-only"',
            ]
        ),
        encoding="utf-8",
    )
    project_config = tmp_path / "pycodex.toml"
    project_config.write_text(
        "\n".join(
            [
                'model = "project-model"',
                'default_approval_policy = "unless-trusted"',
                'default_sandbox_policy = "workspace-write"',
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PYCODEX_MODEL", "env-model")
    monkeypatch.setenv("PYCODEX_DEFAULT_APPROVAL_POLICY", "never")
    monkeypatch.setenv("PYCODEX_DEFAULT_SANDBOX_POLICY", "danger-full-access")

    config = load_config(config_path=project_config, global_config_path=global_config)

    assert config.model == "env-model"
    assert config.default_approval_policy == ApprovalPolicy.NEVER
    assert config.default_sandbox_policy == SandboxPolicy.DANGER_FULL_ACCESS
