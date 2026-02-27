from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def test_cli_live_openai_smoke(tmp_path: Path) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not set")

    if importlib.util.find_spec("openai") is None:
        pytest.skip("openai package is not installed")

    env = os.environ.copy()
    env["PYCODEX_CWD"] = str(tmp_path)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pycodex",
            "Reply with one short sentence that says live e2e is working.",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )

    if proc.returncode != 0 and "Connection error." in proc.stderr:
        pytest.skip("OpenAI endpoint is unreachable from this environment")

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() != ""
    assert "Traceback" not in proc.stderr
