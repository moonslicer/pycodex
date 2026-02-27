from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from pycodex.tools.base import ToolError, ToolResult
from pycodex.tools.grep_files import GrepFilesTool


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True


def _expect_result(outcome: ToolResult | ToolError) -> ToolResult:
    assert isinstance(outcome, ToolResult)
    return outcome


def _expect_error(outcome: ToolResult | ToolError, *, code: str) -> ToolError:
    assert isinstance(outcome, ToolError)
    assert outcome.code == code
    return outcome


async def test_grep_files_tool_returns_matches_sorted_by_mtime(
    tmp_path: Path, monkeypatch: Any
) -> None:
    older = tmp_path / "old.py"
    newer = tmp_path / "new.py"
    older.write_text("def old():\n    pass\n", encoding="utf-8")
    newer.write_text("def new():\n    pass\n", encoding="utf-8")
    os.utime(older, (1_000_000_000, 1_000_000_000))
    os.utime(newer, (1_000_000_100, 1_000_000_100))

    calls: list[tuple[Any, ...]] = []

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        calls.append(args)
        _ = kwargs
        return _FakeProcess(returncode=0, stdout=b"old.py\nnew.py\n")

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rg" if name == "rg" else None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await GrepFilesTool().handle({"pattern": "def "}, tmp_path)
    payload = _expect_result(result).body

    assert payload == {"matches": ["new.py", "old.py"], "truncated": False}
    assert calls
    assert calls[0][0] == "rg"


async def test_grep_files_tool_exit_code_one_means_no_matches(
    tmp_path: Path, monkeypatch: Any
) -> None:
    (tmp_path / "sample.txt").write_text("hello", encoding="utf-8")

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        _ = args, kwargs
        return _FakeProcess(returncode=1)

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rg" if name == "rg" else None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await GrepFilesTool().handle({"pattern": "missing"}, tmp_path)
    payload = _expect_result(result).body

    assert payload == {"matches": [], "truncated": False}


async def test_grep_files_tool_applies_limit_and_sets_truncated_flag(
    tmp_path: Path, monkeypatch: Any
) -> None:
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("match", encoding="utf-8")

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        _ = args, kwargs
        return _FakeProcess(returncode=0, stdout=b"a.txt\nb.txt\nc.txt\n")

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rg" if name == "rg" else None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await GrepFilesTool().handle({"pattern": "match", "limit": 2}, tmp_path)
    payload = _expect_result(result).body

    assert len(payload["matches"]) == 2
    assert payload["truncated"] is True


async def test_grep_files_tool_passes_include_glob_to_rg(tmp_path: Path, monkeypatch: Any) -> None:
    (tmp_path / "a.py").write_text("def hi():\n    pass\n", encoding="utf-8")

    command_calls: list[tuple[Any, ...]] = []

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        command_calls.append(args)
        _ = kwargs
        return _FakeProcess(returncode=0, stdout=b"a.py\n")

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rg" if name == "rg" else None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await GrepFilesTool().handle(
        {"pattern": "def ", "include": "*.py"},
        tmp_path,
    )
    _expect_result(result)

    assert command_calls
    command = list(command_calls[0])
    assert "--glob" in command
    assert "*.py" in command


async def test_grep_files_tool_falls_back_to_grep_when_rg_is_unavailable(
    tmp_path: Path, monkeypatch: Any
) -> None:
    (tmp_path / "a.txt").write_text("needle", encoding="utf-8")

    calls: list[tuple[Any, ...]] = []

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        calls.append(args)
        _ = kwargs
        return _FakeProcess(returncode=0, stdout=b"a.txt\n")

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await GrepFilesTool().handle({"pattern": "needle"}, tmp_path)
    payload = _expect_result(result).body

    assert payload == {"matches": ["a.txt"], "truncated": False}
    assert calls
    assert calls[0][0] == "grep"
    assert "--" in calls[0]


async def test_grep_files_tool_grep_fallback_handles_option_like_patterns(
    tmp_path: Path, monkeypatch: Any
) -> None:
    (tmp_path / "a.txt").write_text("--help marker", encoding="utf-8")

    calls: list[tuple[Any, ...]] = []

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        calls.append(args)
        _ = kwargs
        return _FakeProcess(returncode=0, stdout=b"a.txt\n")

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await GrepFilesTool().handle({"pattern": "--help"}, tmp_path)
    payload = _expect_result(result).body

    assert payload == {"matches": ["a.txt"], "truncated": False}
    assert calls
    assert calls[0][0] == "grep"
    assert "--" in calls[0]
    assert "--help" in calls[0]


async def test_grep_files_tool_timeout_returns_error(tmp_path: Path, monkeypatch: Any) -> None:
    (tmp_path / "a.txt").write_text("needle", encoding="utf-8")
    process = _FakeProcess(returncode=0, stdout=b"a.txt\n")

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> _FakeProcess:
        _ = args, kwargs
        return process

    async def fake_wait_for(awaitable: Any, **kwargs: Any) -> Any:
        _ = kwargs
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rg" if name == "rg" else None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    result = await GrepFilesTool().handle({"pattern": "needle"}, tmp_path)
    error = _expect_error(result, code="timeout")

    assert error.message == "Command timed out after 30000ms"
    assert process.killed is True
