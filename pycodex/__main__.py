"""CLI entry point for pycodex."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from pycodex.core.agent import run_turn
from pycodex.core.config import load_config
from pycodex.core.model_client import ModelClient
from pycodex.core.session import Session
from pycodex.tools.base import ToolRegistry, ToolRouter
from pycodex.tools.read_file import ReadFileTool
from pycodex.tools.shell import ShellTool


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pycodex",
        description="Run one non-interactive pycodex turn.",
    )
    parser.add_argument("prompt", help="User prompt for the model.")
    return parser


def _build_tool_router() -> ToolRouter:
    registry = ToolRegistry()
    registry.register(ShellTool())
    registry.register(ReadFileTool())
    return ToolRouter(registry)


async def _run_prompt(prompt: str) -> str:
    config = load_config()
    session = Session(config=config)
    model_client = ModelClient(config)
    tool_router = _build_tool_router()
    return await run_turn(
        session=session,
        model_client=model_client,
        tool_router=tool_router,
        cwd=config.cwd,
        user_input=prompt,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        final_text = asyncio.run(_run_prompt(args.prompt))
    except Exception as exc:
        message = str(exc).strip() or type(exc).__name__
        print(f"[ERROR] {message}", file=sys.stderr)
        return 1
    print(final_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
