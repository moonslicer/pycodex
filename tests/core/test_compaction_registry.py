from __future__ import annotations

import pytest
from pycodex.core.compaction import (
    DEFAULT_COMPACTION_IMPLEMENTATION,
    DEFAULT_COMPACTION_STRATEGY,
    IMPLEMENTATION_REGISTRY,
    STRATEGY_REGISTRY,
    create_compaction_orchestrator,
)


def test_registry_exposes_default_component_names() -> None:
    assert DEFAULT_COMPACTION_STRATEGY in STRATEGY_REGISTRY
    assert DEFAULT_COMPACTION_IMPLEMENTATION in IMPLEMENTATION_REGISTRY


def test_create_compaction_orchestrator_uses_default_components() -> None:
    orchestrator = create_compaction_orchestrator()

    assert orchestrator.strategy.name == DEFAULT_COMPACTION_STRATEGY
    assert orchestrator.implementation.name == DEFAULT_COMPACTION_IMPLEMENTATION


def test_create_compaction_orchestrator_rejects_unknown_strategy() -> None:
    with pytest.raises(ValueError, match="Unknown compaction strategy"):
        create_compaction_orchestrator(strategy_name="unknown")


def test_create_compaction_orchestrator_rejects_unknown_implementation() -> None:
    with pytest.raises(ValueError, match="Unknown compaction implementation"):
        create_compaction_orchestrator(implementation_name="unknown")


def test_create_compaction_orchestrator_applies_component_options() -> None:
    orchestrator = create_compaction_orchestrator(
        strategy_options={"threshold_ratio": 0.05, "keep_recent_items": 4},
        implementation_options={"max_lines": 3},
    )

    assert orchestrator.strategy.threshold_ratio == 0.05
    assert orchestrator.strategy.keep_recent_items == 4
    assert orchestrator.implementation.max_lines == 3
