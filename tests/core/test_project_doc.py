from __future__ import annotations

from pathlib import Path

from pycodex.core.project_doc import (
    PROJECT_DOC_SEPARATOR,
    find_git_root,
    load_project_instructions,
)


def test_find_git_root_returns_none_when_no_repo(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert find_git_root(nested) is None


def test_load_project_instructions_without_git_root_reads_cwd_only(tmp_path: Path) -> None:
    cwd = tmp_path / "project"
    cwd.mkdir()
    (cwd / "AGENTS.md").write_text("cwd instructions", encoding="utf-8")
    parent_file = tmp_path / "AGENTS.md"
    parent_file.write_text("parent instructions", encoding="utf-8")

    loaded = load_project_instructions(cwd)

    assert loaded == "cwd instructions"


def test_load_project_instructions_walks_repo_root_to_cwd_in_order(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    cwd = root / "pkg" / "feature"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("root", encoding="utf-8")
    (root / "pkg" / "AGENTS.md").write_text("pkg", encoding="utf-8")
    (cwd / "AGENTS.md").write_text("feature", encoding="utf-8")

    loaded = load_project_instructions(cwd)

    assert loaded == PROJECT_DOC_SEPARATOR.join(["root", "pkg", "feature"])


def test_load_project_instructions_returns_none_when_no_files_found(tmp_path: Path) -> None:
    cwd = tmp_path / "repo" / "pkg"
    cwd.mkdir(parents=True)
    (tmp_path / "repo" / ".git").mkdir()

    loaded = load_project_instructions(cwd)

    assert loaded is None


def test_load_project_instructions_truncates_by_max_bytes(tmp_path: Path) -> None:
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)
    (cwd / ".git").mkdir()
    (cwd / "AGENTS.md").write_text("x" * 500, encoding="utf-8")

    loaded = load_project_instructions(cwd, max_bytes=50)

    assert loaded is not None
    assert loaded.endswith("\n[truncated]")
    assert len(loaded.encode("utf-8")) <= 50


def test_load_project_instructions_skips_unreadable_file(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    cwd = root / "pkg"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    unreadable = root / "AGENTS.md"
    readable = cwd / "AGENTS.md"
    unreadable.write_text("root", encoding="utf-8")
    readable.write_text("pkg", encoding="utf-8")

    original_read_text = Path.read_text

    def _fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == unreadable:
            raise OSError("permission denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _fake_read_text)

    loaded = load_project_instructions(cwd)

    assert loaded == "pkg"


def test_load_project_instructions_when_cwd_is_git_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("root", encoding="utf-8")

    loaded = load_project_instructions(root)

    assert loaded == "root"


def test_load_project_instructions_checks_multiple_filenames_per_level(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    cwd = root / "pkg"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "TEAM.md").write_text("team-root", encoding="utf-8")
    (root / "AGENTS.md").write_text("agents-root", encoding="utf-8")
    (cwd / "TEAM.md").write_text("team-pkg", encoding="utf-8")

    loaded = load_project_instructions(cwd, filenames=("TEAM.md", "AGENTS.md"))

    assert loaded == PROJECT_DOC_SEPARATOR.join(["team-root", "agents-root", "team-pkg"])


def test_load_project_instructions_honors_custom_filename_list(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    cwd = root / "pkg"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("agents-root", encoding="utf-8")
    (root / "SUPPORT.md").write_text("support-root", encoding="utf-8")

    loaded = load_project_instructions(cwd, filenames=("SUPPORT.md",))

    assert loaded == "support-root"


def test_load_project_instructions_rejects_non_positive_max_bytes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("root", encoding="utf-8")

    assert load_project_instructions(root, max_bytes=0) is None
