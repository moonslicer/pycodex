from __future__ import annotations

from pathlib import Path

from pycodex.core.config import Config, load_config


def test_config_defaults() -> None:
    config = Config()
    assert config.model == "gpt-4.1-mini"
    assert config.api_key is None
    assert config.api_base_url is None
    assert isinstance(config.cwd, Path)


def test_load_config_missing_toml_uses_defaults_and_env(monkeypatch) -> None:
    monkeypatch.delenv("PYCODEX_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("PYCODEX_CWD", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    config = load_config(config_path=Path("does-not-exist.toml"))
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

    config = load_config(config_path=config_file)
    assert config.model == "env-model"
    assert config.api_key == "env-key"  # pragma: allowlist secret
    assert config.api_base_url == "https://env.example"
    assert config.cwd == tmp_path


def test_load_config_env_cwd_is_parsed_as_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PYCODEX_CWD", str(tmp_path))
    config = load_config(config_path=Path("does-not-exist.toml"))
    assert config.cwd == tmp_path
