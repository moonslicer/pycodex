from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from pycodex.tools.base import ToolError, ToolResult
from pycodex.tools.grep_files import GrepFilesTool

pytestmark = pytest.mark.integration


def _expect_result(outcome: ToolResult | ToolError) -> ToolResult:
    assert isinstance(outcome, ToolResult)
    return outcome


async def test_grep_files_tool_integration_with_rg(tmp_path: Path) -> None:
    if shutil.which("rg") is None:
        pytest.skip("rg is not installed in PATH")

    old_file = tmp_path / "old.py"
    new_file = tmp_path / "new.py"
    ignored = tmp_path / "ignore.txt"

    old_file.write_text("def old():\n    return 1\n", encoding="utf-8")
    new_file.write_text("def new():\n    return 2\n", encoding="utf-8")
    ignored.write_text("def text_file()\n", encoding="utf-8")

    os.utime(old_file, (1_000_000_000, 1_000_000_000))
    os.utime(new_file, (1_000_000_100, 1_000_000_100))

    outcome = await GrepFilesTool().handle(
        {"pattern": "def ", "path": ".", "include": "*.py"},
        tmp_path,
    )
    payload = _expect_result(outcome).body

    assert payload == {
        "matches": ["new.py", "old.py"],
        "truncated": False,
    }


async def test_grep_files_tool_integration_grep_fallback_via_path(tmp_path: Path) -> None:
    grep_bin = shutil.which("grep")
    if grep_bin is None:
        pytest.skip("grep is not installed in PATH")

    rg_bin = shutil.which("rg")
    if rg_bin is not None and Path(rg_bin).parent == Path(grep_bin).parent:
        pytest.skip("cannot force grep fallback because rg is in the same PATH directory")

    target_file = tmp_path / "target.txt"
    target_file.write_text("--help marker\n", encoding="utf-8")

    previous_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(Path(grep_bin).parent)
    try:
        outcome = await GrepFilesTool().handle(
            {"pattern": "--help", "path": "."},
            tmp_path,
        )
    finally:
        os.environ["PATH"] = previous_path

    payload = _expect_result(outcome).body
    assert payload == {
        "matches": ["target.txt"],
        "truncated": False,
    }
