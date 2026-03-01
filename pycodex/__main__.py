"""CLI entry point for pycodex."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pycodex.approval.policy import ApprovalPolicy, ApprovalStore, ReviewDecision
from pycodex.core.agent import AgentEvent, SupportsModelClient, run_turn
from pycodex.core.config import Config, load_config
from pycodex.core.event_adapter import EventAdapter
from pycodex.core.fake_model_client import FakeModelClient
from pycodex.core.model_client import ModelClient
from pycodex.core.session import Session
from pycodex.core.tui_bridge import TuiBridge
from pycodex.protocol.events import ProtocolEvent
from pycodex.tools.base import ToolRegistry, ToolRouter
from pycodex.tools.grep_files import GrepFilesTool
from pycodex.tools.list_dir import ListDirTool
from pycodex.tools.orchestrator import OrchestratorConfig
from pycodex.tools.read_file import ReadFileTool
from pycodex.tools.shell import ShellTool
from pycodex.tools.write_file import WriteFileTool

EXPECTED_TOOL_NAMES = {"shell", "read_file", "write_file", "list_dir", "grep_files"}
AskUserFn = Callable[[Any, dict[str, Any]], Awaitable[ReviewDecision]]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pycodex",
        description="Run one non-interactive pycodex turn.",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="User prompt for the model (required unless --tui-mode).",
    )
    parser.add_argument(
        "--approval",
        default=ApprovalPolicy.NEVER.value,
        choices=[policy.value for policy in ApprovalPolicy],
        help="Approval policy for mutating tools (default: never).",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("PYCODEX_LOG_LEVEL", "WARNING"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: WARNING; env: PYCODEX_LOG_LEVEL).",
    )
    parser.add_argument(
        "--log-filter",
        default=None,
        metavar="PREFIX",
        help=(
            "Only emit log records whose logger name starts with PREFIX. "
            "Example: --log-filter pycodex silences httpcore, httpx, openai, asyncio. "
            "Omit to show all loggers."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit line-delimited protocol JSON events (requires prompt).",
    )
    parser.add_argument(
        "--tui-mode",
        action="store_true",
        help="Run in interactive TUI bridge mode (no prompt).",
    )
    return parser


def _build_tool_router(
    *,
    approval_policy: ApprovalPolicy,
    ask_user_fn: AskUserFn | None = None,
) -> ToolRouter:
    orchestrator = OrchestratorConfig(
        policy=approval_policy,
        store=ApprovalStore(),
        ask_user_fn=ask_user_fn if ask_user_fn is not None else _ask_user_for_review,
    )
    registry = ToolRegistry(orchestrator=orchestrator)
    _register_default_tools(registry)
    return ToolRouter(registry)


def _register_default_tools(registry: ToolRegistry) -> None:
    registry.register(ShellTool())
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirTool())
    registry.register(GrepFilesTool())


async def _run_prompt(prompt: str, *, approval_policy: ApprovalPolicy) -> str:
    config, session, model_client, tool_router = _build_runtime(approval_policy=approval_policy)
    return await run_turn(
        session=session,
        model_client=model_client,
        tool_router=tool_router,
        cwd=config.cwd,
        user_input=prompt,
    )


def _build_runtime(
    *,
    approval_policy: ApprovalPolicy,
) -> tuple[Config, Session, SupportsModelClient, ToolRouter]:
    config = load_config()
    session = Session(config=config)
    model_client = _build_model_client(config)
    tool_router = _build_tool_router(approval_policy=approval_policy)
    return config, session, model_client, tool_router


def _build_model_client(config: Config) -> SupportsModelClient:
    if _is_fake_model_enabled():
        return FakeModelClient(config)
    return ModelClient(config)


def _is_fake_model_enabled() -> bool:
    raw = os.environ.get("PYCODEX_FAKE_MODEL")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _emit_protocol_event(event: ProtocolEvent) -> None:
    sys.stdout.write(f"{event.model_dump_json()}\n")


def _render_error_message(exc: Exception) -> str:
    return str(exc).strip() or type(exc).__name__


async def _run_prompt_json(prompt: str, *, approval_policy: ApprovalPolicy) -> int:
    config, session, model_client, tool_router = _build_runtime(approval_policy=approval_policy)
    adapter = EventAdapter()

    _emit_protocol_event(adapter.start_thread())

    def on_event(event: AgentEvent) -> None:
        for protocol_event in adapter.on_agent_event(event):
            _emit_protocol_event(protocol_event)

    try:
        await run_turn(
            session=session,
            model_client=model_client,
            tool_router=tool_router,
            cwd=config.cwd,
            user_input=prompt,
            on_event=on_event,
        )
    except Exception as exc:
        _emit_protocol_event(adapter.turn_failed(exc))
        return 1
    return 0


async def _run_tui_mode(*, approval_policy: ApprovalPolicy) -> int:
    config = load_config()
    session = Session(config=config)
    model_client = _build_model_client(config)
    bridge: TuiBridge | None = None

    async def _tui_ask_user_fn(tool: Any, args: dict[str, Any]) -> ReviewDecision:
        assert bridge is not None
        return await bridge.request_approval(tool, args)

    tool_router = _build_tool_router(
        approval_policy=approval_policy,
        ask_user_fn=_tui_ask_user_fn,
    )
    bridge = TuiBridge(
        session=session,
        model_client=model_client,
        tool_router=tool_router,
        cwd=config.cwd,
    )
    await bridge.run()
    return 0


def _parse_review_decision(raw_value: str) -> ReviewDecision:
    normalized = raw_value.strip().lower()
    if normalized in {"y", "yes"}:
        return ReviewDecision.APPROVED
    if normalized in {"s", "session"}:
        return ReviewDecision.APPROVED_FOR_SESSION
    if normalized in {"a", "abort"}:
        return ReviewDecision.ABORT
    return ReviewDecision.DENIED


def _approval_prompt(tool_name: str, args: dict[str, Any]) -> str:
    rendered_args = json.dumps(args, sort_keys=True, ensure_ascii=True)
    return f"Approve tool '{tool_name}' with args {rendered_args}? [y]es/[s]ession/[n]o/[a]bort: "


async def _ask_user_for_review(tool: Any, args: dict[str, Any]) -> ReviewDecision:
    response = await asyncio.to_thread(input, _approval_prompt(tool.name, args))
    return _parse_review_decision(response)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(
        level=args.log_level,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.log_filter:
        _prefix = args.log_filter

        class _PrefixFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                return record.name.startswith(_prefix)

        logging.getLogger().handlers[0].addFilter(_PrefixFilter())
    approval_policy = ApprovalPolicy(args.approval)
    if args.tui_mode:
        if args.json:
            parser.error("--json cannot be used with --tui-mode")
        if args.prompt is not None:
            parser.error("prompt is not accepted with --tui-mode")
        try:
            return asyncio.run(
                _run_tui_mode(
                    approval_policy=approval_policy,
                )
            )
        except Exception as exc:
            message = _render_error_message(exc)
            print(f"[ERROR] {message}", file=sys.stderr)
            return 1

    if args.prompt is None:
        parser.error("the following arguments are required: prompt")
    prompt: str = args.prompt

    if args.json:
        try:
            return asyncio.run(
                _run_prompt_json(
                    prompt,
                    approval_policy=approval_policy,
                )
            )
        except Exception as exc:
            message = _render_error_message(exc)
            print(f"[ERROR] {message}", file=sys.stderr)
            return 1

    try:
        final_text = asyncio.run(
            _run_prompt(
                prompt,
                approval_policy=approval_policy,
            )
        )
    except Exception as exc:
        message = _render_error_message(exc)
        print(f"[ERROR] {message}", file=sys.stderr)
        return 1
    print(final_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
