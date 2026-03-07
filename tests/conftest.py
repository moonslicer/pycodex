from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_home_for_tests(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep test rollouts/config under pytest temp dirs, never real ~/.pycodex."""
    home = str(tmp_path)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)
