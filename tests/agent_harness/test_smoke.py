import pytest

pytestmark = pytest.mark.agent_harness


def test_agent_harness_smoke() -> None:
    """Starter harness test so the harness gate has a runnable baseline."""
    assert True
