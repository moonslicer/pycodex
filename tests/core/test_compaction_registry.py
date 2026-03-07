from __future__ import annotations

from dataclasses import dataclass

import pytest
from pycodex.core.compaction import (
    DEFAULT_COMPACTION_IMPLEMENTATION,
    DEFAULT_COMPACTION_STRATEGY,
    IMPLEMENTATION_REGISTRY,
    MODEL_SUMMARY_V1_IMPLEMENTATION,
    STRATEGY_REGISTRY,
    LocalSummaryV1Implementation,
    create_compaction_orchestrator,
)


@dataclass(slots=True)
class _FakeModelCompleteClient:
    async def complete(
        self,
        messages: list[dict[str, object]],
        *,
        instructions: str = "",
        max_output_tokens: int = 4096,
    ) -> str:
        _ = messages, instructions, max_output_tokens
        return "<summary>ok</summary>"


def test_registry_exposes_default_component_names() -> None:
    assert DEFAULT_COMPACTION_STRATEGY in STRATEGY_REGISTRY
    assert DEFAULT_COMPACTION_IMPLEMENTATION in IMPLEMENTATION_REGISTRY
    assert MODEL_SUMMARY_V1_IMPLEMENTATION in IMPLEMENTATION_REGISTRY


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


def test_create_compaction_orchestrator_rejects_model_summary_without_model_client() -> None:
    with pytest.raises(ValueError, match="requires a model_client"):
        create_compaction_orchestrator(implementation_name=MODEL_SUMMARY_V1_IMPLEMENTATION)


def test_create_compaction_orchestrator_builds_model_summary_with_options() -> None:
    orchestrator = create_compaction_orchestrator(
        implementation_name=MODEL_SUMMARY_V1_IMPLEMENTATION,
        implementation_options={
            "max_output_tokens": 256,
            "custom_instructions": "Focus on code changes.",
        },
        model_client=_FakeModelCompleteClient(),
    )

    assert orchestrator.implementation.name == MODEL_SUMMARY_V1_IMPLEMENTATION
    assert orchestrator.implementation.max_output_tokens == 256
    assert orchestrator.implementation.custom_instructions == "Focus on code changes."


def test_create_compaction_orchestrator_supports_legacy_implementation_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _legacy_factory(options: dict[str, object]) -> LocalSummaryV1Implementation:
        return LocalSummaryV1Implementation(max_lines=int(options.get("max_lines", 8)))

    implementation_name = "legacy_local_summary_test"
    monkeypatch.setitem(IMPLEMENTATION_REGISTRY, implementation_name, _legacy_factory)

    orchestrator = create_compaction_orchestrator(
        implementation_name=implementation_name,
        implementation_options={"max_lines": 5},
    )

    assert orchestrator.implementation.name == DEFAULT_COMPACTION_IMPLEMENTATION
    assert orchestrator.implementation.max_lines == 5


def test_create_compaction_orchestrator_supports_var_keyword_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory with (options, **kwargs) must not be called with two positional args."""

    def _kwargs_factory(options: dict[str, object], **kwargs: object) -> LocalSummaryV1Implementation:
        return LocalSummaryV1Implementation(max_lines=int(options.get("max_lines", 8)))

    monkeypatch.setitem(IMPLEMENTATION_REGISTRY, "kwargs_factory_test", _kwargs_factory)

    orchestrator = create_compaction_orchestrator(
        implementation_name="kwargs_factory_test",
        implementation_options={"max_lines": 3},
    )

    assert orchestrator.implementation.max_lines == 3


def test_create_compaction_orchestrator_supports_keyword_only_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory with (options, *, model_client=None) must not be called with two positional args."""

    def _kwonly_factory(
        options: dict[str, object], *, model_client: object = None
    ) -> LocalSummaryV1Implementation:
        return LocalSummaryV1Implementation(max_lines=int(options.get("max_lines", 8)))

    monkeypatch.setitem(IMPLEMENTATION_REGISTRY, "kwonly_factory_test", _kwonly_factory)

    orchestrator = create_compaction_orchestrator(
        implementation_name="kwonly_factory_test",
        implementation_options={"max_lines": 4},
    )

    assert orchestrator.implementation.max_lines == 4
