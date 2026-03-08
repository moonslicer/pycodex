from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from pycodex.approval.policy import ApprovalPolicy
from pycodex.approval.sandbox import SandboxPolicy
from pycodex.core.agent_profile import CODEX_PROFILE, AgentProfile
from pycodex.core.initial_context import build_initial_context
from pycodex.core.skills.manager import SkillRegistry
from pycodex.core.skills.models import SkillMetadata


@dataclass(slots=True)
class _SkillsManagerStub:
    registry: SkillRegistry

    def get_registry(self, **_: object) -> SkillRegistry:
        return self.registry


@dataclass(slots=True)
class _ConfigStub:
    cwd: Path
    profile: AgentProfile = CODEX_PROFILE
    project_doc_max_bytes: int = 32_768
    approval_policy: ApprovalPolicy | str | None = None
    sandbox_policy: SandboxPolicy | str | None = None
    skills_manager: _SkillsManagerStub = field(
        default_factory=lambda: _SkillsManagerStub(registry=_registry(()))
    )
    skill_dirs: tuple[()] = ()
    skills_user_root: Path | None = None
    skills_system_root: Path | None = None


def test_build_initial_context_default_no_docs_returns_env_context_only(tmp_path: Path) -> None:
    config = _ConfigStub(cwd=tmp_path)

    items = build_initial_context(config)  # type: ignore[arg-type]

    assert len(items) == 1
    assert items[0]["role"] == "system"
    assert "# Environment context" in items[0]["content"]
    assert str(tmp_path) in items[0]["content"]


def test_build_initial_context_includes_policy_context_when_non_default(tmp_path: Path) -> None:
    config = _ConfigStub(
        cwd=tmp_path,
        approval_policy=ApprovalPolicy.ON_REQUEST,
        sandbox_policy=SandboxPolicy.READ_ONLY,
    )

    items = build_initial_context(config)  # type: ignore[arg-type]

    assert len(items) == 2
    assert "# Policy context" in items[0]["content"]
    assert "approval policy: on-request" in items[0]["content"]
    assert "sandbox policy: read-only" in items[0]["content"]


def test_build_initial_context_loads_project_docs_for_default_profile(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    cwd = root / "pkg"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("root instructions", encoding="utf-8")
    config = _ConfigStub(cwd=cwd)

    items = build_initial_context(config)  # type: ignore[arg-type]

    assert len(items) == 2
    assert items[0]["role"] == "system"
    assert items[0]["content"].startswith("# Project instructions\n")
    assert "root instructions" in items[0]["content"]


def test_build_initial_context_uses_profile_specific_filenames(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    cwd = root / "pkg"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("agents instructions", encoding="utf-8")
    (root / "SUPPORT.md").write_text("support instructions", encoding="utf-8")
    profile = AgentProfile(
        name="support",
        instructions="Support role.",
        instruction_filenames=("SUPPORT.md",),
        enabled_tools=None,
    )
    config = _ConfigStub(cwd=cwd, profile=profile)

    items = build_initial_context(config)  # type: ignore[arg-type]

    assert len(items) == 2
    assert "support instructions" in items[0]["content"]
    assert "agents instructions" not in items[0]["content"]


def test_build_initial_context_orders_policy_docs_env(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    cwd = root / "pkg"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("root instructions", encoding="utf-8")
    config = _ConfigStub(
        cwd=cwd,
        approval_policy=ApprovalPolicy.UNLESS_TRUSTED,
        sandbox_policy=SandboxPolicy.WORKSPACE_WRITE,
    )

    items = build_initial_context(config)  # type: ignore[arg-type]

    assert [item["role"] for item in items] == ["system", "system", "system"]
    assert "# Policy context" in items[0]["content"]
    assert "# Project instructions" in items[1]["content"]
    assert "# Environment context" in items[2]["content"]


def test_build_initial_context_appends_skills_to_project_instructions(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    cwd = root / "pkg"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("root instructions", encoding="utf-8")

    skills_manager = _SkillsManagerStub(
        registry=_registry((_skill("alpha", "Alpha description", "Alpha short"),))
    )
    config = _ConfigStub(cwd=cwd, skills_manager=skills_manager)

    items = build_initial_context(config)  # type: ignore[arg-type]

    assert len(items) == 2
    content = items[0]["content"]
    assert content.startswith("# Project instructions\n")
    assert "root instructions" in content
    assert "## Skills" in content
    assert "- alpha: Alpha description — Alpha short" in content


def test_build_initial_context_adds_skills_section_when_no_project_docs(tmp_path: Path) -> None:
    skills_manager = _SkillsManagerStub(
        registry=_registry((_skill("beta", "Beta description", None),))
    )
    config = _ConfigStub(cwd=tmp_path, skills_manager=skills_manager)

    items = build_initial_context(config)  # type: ignore[arg-type]

    assert len(items) == 2
    assert items[0]["content"].startswith("## Skills\n")
    assert "- beta: Beta description" in items[0]["content"]
    assert "# Environment context" in items[1]["content"]


def test_build_initial_context_omits_skills_when_registry_empty(tmp_path: Path) -> None:
    config = _ConfigStub(cwd=tmp_path, skills_manager=_SkillsManagerStub(registry=_registry(())))

    items = build_initial_context(config)  # type: ignore[arg-type]

    assert len(items) == 1
    assert "## Skills" not in items[0]["content"]


def _skill(name: str, description: str, short_description: str | None) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=description,
        short_description=short_description,
        path_to_skill_md=Path(f"/tmp/{name}/SKILL.md"),
        skill_root=Path(f"/tmp/{name}"),
        scope="repo",
    )


def _registry(skills: tuple[SkillMetadata, ...]) -> SkillRegistry:
    by_name = {skill.name: skill for skill in skills}
    by_path = {skill.path_to_skill_md: skill for skill in skills}
    return SkillRegistry(
        skills=skills,
        errors=(),
        ambiguous_names=frozenset(),
        by_name=MappingProxyType(by_name),
        by_path=MappingProxyType(by_path),
    )
