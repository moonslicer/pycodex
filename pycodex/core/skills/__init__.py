"""Skills models and parsing helpers."""

from pycodex.core.skills.discovery import (
    SkillDiscoveryResult,
    SkillRoot,
    collect_skill_roots,
    discover_skills,
)
from pycodex.core.skills.injector import (
    SkillInjectedMessage,
    SkillInjectionPlan,
    build_skill_injection_plan,
)
from pycodex.core.skills.manager import SkillRegistry, SkillsManager
from pycodex.core.skills.models import (
    SkillDependencies,
    SkillEnvVarDependency,
    SkillLoadOutcome,
    SkillMetadata,
    SkillScope,
)
from pycodex.core.skills.parser import (
    ParsedSkillDocument,
    SkillParseError,
    parse_skill_markdown,
)
from pycodex.core.skills.render import render_skills_section
from pycodex.core.skills.resolver import (
    SkillMention,
    SkillResolutionResult,
    UnresolvedSkillMention,
    extract_skill_mentions,
    resolve_skill_mentions,
)

__all__ = [
    "ParsedSkillDocument",
    "SkillDependencies",
    "SkillDiscoveryResult",
    "SkillEnvVarDependency",
    "SkillInjectedMessage",
    "SkillInjectionPlan",
    "SkillLoadOutcome",
    "SkillMention",
    "SkillMetadata",
    "SkillParseError",
    "SkillRegistry",
    "SkillResolutionResult",
    "SkillRoot",
    "SkillScope",
    "SkillsManager",
    "UnresolvedSkillMention",
    "build_skill_injection_plan",
    "collect_skill_roots",
    "discover_skills",
    "extract_skill_mentions",
    "parse_skill_markdown",
    "render_skills_section",
    "resolve_skill_mentions",
]
