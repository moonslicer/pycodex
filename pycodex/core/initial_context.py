"""Initial system-context assembly for session startup."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pycodex.approval.policy import ApprovalPolicy
from pycodex.approval.sandbox import SandboxPolicy
from pycodex.core.project_doc import load_project_instructions
from pycodex.core.session import PromptItem
from pycodex.core.skills.manager import SkillsManager
from pycodex.core.skills.render import render_skills_section

if TYPE_CHECKING:
    from pycodex.core.config import Config


def build_initial_context(config: Config) -> list[PromptItem]:
    """Assemble system context items in deterministic order."""
    items: list[PromptItem] = []

    policy = _policy_context(config)
    if policy is not None:
        items.append({"role": "system", "content": policy})

    project_docs = load_project_instructions(
        config.cwd,
        filenames=config.profile.instruction_filenames,
        max_bytes=config.project_doc_max_bytes,
    )
    if project_docs is not None:
        items.append(
            {
                "role": "system",
                "content": f"# Project instructions\n{project_docs}",
            }
        )

    items.append({"role": "system", "content": _env_context(config.cwd)})

    skills_section = _skills_context(config)
    if skills_section is not None:
        items.append({"role": "system", "content": skills_section})

    return items


def _env_context(cwd: os.PathLike[str] | str) -> str:
    shell = os.environ.get("SHELL", "sh")
    os_name = platform.system() or sys.platform
    python_version = platform.python_version()
    return "\n".join(
        [
            "# Environment context",
            f"- cwd: {cwd}",
            f"- shell: {shell}",
            f"- os: {os_name}",
            f"- python: {python_version}",
        ]
    )


def _policy_context(config: object) -> str | None:
    approval_policy = _normalize_policy_value(getattr(config, "approval_policy", None))
    sandbox_policy = _normalize_policy_value(getattr(config, "sandbox_policy", None))

    if approval_policy in {None, ApprovalPolicy.NEVER.value} and sandbox_policy in {
        None,
        SandboxPolicy.DANGER_FULL_ACCESS.value,
    }:
        return None

    lines = ["# Policy context"]
    if approval_policy is not None:
        lines.append(f"- approval policy: {approval_policy}")
    if sandbox_policy is not None:
        lines.append(f"- sandbox policy: {sandbox_policy}")
    return "\n".join(lines)


def _normalize_policy_value(value: object) -> str | None:
    if isinstance(value, (ApprovalPolicy, SandboxPolicy)):
        return value.value
    if isinstance(value, str) and value:
        return value
    return None


def _skills_context(config: Config) -> str | None:
    manager = config.skills_manager or SkillsManager()
    try:
        registry = manager.get_registry(
            cwd=Path(config.cwd),
            project_skill_dirs=config.skill_dirs,
            user_root=config.skills_user_root,
            system_root=config.skills_system_root,
        )
    except Exception:
        return None
    return render_skills_section(registry.skills)
