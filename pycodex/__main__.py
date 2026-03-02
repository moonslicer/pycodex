"""CLI entry point for pycodex."""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import logging
import os
import shutil
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from pycodex.approval.exec_policy import DEFAULT_RULES, classify, default_heuristics
from pycodex.approval.policy import ApprovalPolicy, ApprovalStore, ReviewDecision
from pycodex.approval.sandbox import SandboxPolicy
from pycodex.core.agent import AgentEvent, SupportsModelClient, run_turn
from pycodex.core.agent_profile import CODEX_PROFILE, AgentProfile, load_profile_from_toml
from pycodex.core.config import Config, load_config
from pycodex.core.event_adapter import EventAdapter
from pycodex.core.fake_model_client import FakeModelClient
from pycodex.core.model_client import ModelClient
from pycodex.core.rollout_recorder import (
    RolloutRecorder,
    build_rollout_path,
    default_archived_sessions_root,
    default_sessions_root,
    resolve_latest_rollout,
)
from pycodex.core.rollout_replay import (
    RolloutReplayError,
    import_legacy_session_json,
    replay_rollout,
)
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
BUILTIN_PROFILES: dict[str, AgentProfile] = {"codex": CODEX_PROFILE}
AskUserFn = Callable[[Any, dict[str, Any]], Awaitable[ReviewDecision]]
INTERRUPTED_EXIT_CODE = 130
INTERRUPTED_ERROR = "interrupted"


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
        "prompt_tail",
        nargs="*",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--approval",
        default=None,
        choices=[policy.value for policy in ApprovalPolicy],
        help="Approval policy for mutating tools (default: resolved from config).",
    )
    parser.add_argument(
        "--sandbox",
        default=None,
        choices=[policy.value for policy in SandboxPolicy],
        help="Sandbox policy for tool execution (default: resolved from config).",
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
        "--dump-llm-request",
        action="store_true",
        help="Write the raw LLM request payload to stderr before each model call.",
    )
    parser.add_argument(
        "--resume",
        default=None,
        metavar="THREAD_OR_PATH",
        help="Resume from latest rollout by thread ID or explicit rollout path.",
    )
    parser.add_argument(
        "--tui-mode",
        action="store_true",
        help="Run in interactive TUI bridge mode (no prompt).",
    )
    profile_group = parser.add_mutually_exclusive_group()
    profile_group.add_argument(
        "--profile",
        default=None,
        metavar="NAME",
        help="Use a built-in profile name (for example: codex).",
    )
    profile_group.add_argument(
        "--profile-file",
        default=None,
        metavar="PATH",
        help="Load profile definition from TOML file.",
    )
    instructions_group = parser.add_mutually_exclusive_group()
    instructions_group.add_argument(
        "--instructions",
        default=None,
        metavar="TEXT",
        help="Override the active profile instructions inline.",
    )
    instructions_group.add_argument(
        "--instructions-file",
        default=None,
        metavar="PATH",
        help="Load instruction override text from file.",
    )
    return parser


def _build_tool_router(
    *,
    approval_policy: ApprovalPolicy,
    sandbox_policy: SandboxPolicy,
    ask_user_fn: AskUserFn | None = None,
) -> ToolRouter:
    orchestrator = OrchestratorConfig(
        policy=approval_policy,
        store=ApprovalStore(),
        ask_user_fn=ask_user_fn if ask_user_fn is not None else _ask_user_for_review,
        exec_policy_fn=functools.partial(
            classify,
            rules=DEFAULT_RULES,
            heuristics=default_heuristics,
        ),
        sandbox_policy=sandbox_policy,
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


async def _run_prompt(
    prompt: str,
    *,
    approval_policy: ApprovalPolicy,
    sandbox_policy: SandboxPolicy,
    dump_llm_request: bool = False,
    profile: str | None = None,
    profile_file: str | None = None,
    instructions: str | None = None,
    instructions_file: str | None = None,
    resume: str | None = None,
) -> str:
    config, session, model_client, tool_router = await _build_runtime(
        approval_policy=approval_policy,
        sandbox_policy=sandbox_policy,
        dump_llm_request=dump_llm_request,
        profile=profile,
        profile_file=profile_file,
        instructions=instructions,
        instructions_file=instructions_file,
        resume=resume,
    )
    try:
        return await run_turn(
            session=session,
            model_client=model_client,
            tool_router=tool_router,
            cwd=config.cwd,
            user_input=prompt,
        )
    finally:
        await session.close_rollout()


async def _build_runtime(
    *,
    approval_policy: ApprovalPolicy,
    sandbox_policy: SandboxPolicy,
    dump_llm_request: bool = False,
    profile: str | None = None,
    profile_file: str | None = None,
    instructions: str | None = None,
    instructions_file: str | None = None,
    resume: str | None = None,
) -> tuple[Config, Session, SupportsModelClient, ToolRouter]:
    config = _resolve_runtime_config(
        profile=profile,
        profile_file=profile_file,
        instructions=instructions,
        instructions_file=instructions_file,
    )
    session = await _build_session(config=config, resume=resume)
    model_client = _build_model_client(config, dump_llm_request=dump_llm_request)
    tool_router = _build_tool_router(
        approval_policy=approval_policy,
        sandbox_policy=sandbox_policy,
    )
    return config, session, model_client, tool_router


async def _build_session(*, config: Config, resume: str | None) -> Session:
    if resume is None:
        session = Session(config=config)
        _configure_rollout_persistence(session, config=config)
        return session

    rollout_path = await _resolve_resume_rollout_path(config=config, resume=resume)
    replay_state = replay_rollout(rollout_path)
    session = Session(config=config, thread_id=replay_state.thread_id)
    session.restore_from_rollout(
        history=replay_state.history,
        cumulative_usage=replay_state.cumulative_usage,
        turn_count=replay_state.turn_count,
    )
    _configure_rollout_persistence(session, config=config, resume_path=rollout_path)
    session.mark_rollout_meta_written()
    return session


def _build_model_client(config: Config, *, dump_llm_request: bool = False) -> SupportsModelClient:
    if _is_fake_model_enabled():
        return FakeModelClient(config)
    request_observer = _dump_llm_request_to_stderr if dump_llm_request else None
    return ModelClient(config, request_observer=request_observer)


def _configure_rollout_persistence(
    session: Session,
    *,
    config: Config,
    resume_path: Path | None = None,
) -> None:
    sessions_root = _resolve_sessions_root(config)
    path = resume_path or build_rollout_path(session.thread_id, root=sessions_root)
    session.configure_rollout_recorder(
        recorder=RolloutRecorder(path=path),
        path=path,
    )


def _resolve_sessions_root(config: Config) -> Path:
    preferred = default_sessions_root()
    if _ensure_directory(preferred):
        return preferred
    fallback = config.cwd / ".pycodex" / "sessions"
    _ensure_directory(fallback)
    return fallback


def _resolve_archived_sessions_root(config: Config) -> Path:
    preferred = default_archived_sessions_root()
    if _ensure_directory(preferred):
        return preferred
    fallback = config.cwd / ".pycodex" / "archived_sessions"
    _ensure_directory(fallback)
    return fallback


def _ensure_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return True


def _is_fake_model_enabled() -> bool:
    raw = os.environ.get("PYCODEX_FAKE_MODEL")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _dump_llm_request_to_stderr(payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, default=str)
    sys.stderr.write(f"[llm-request] {rendered}\n")


def _resolve_runtime_config(
    *,
    profile: str | None,
    profile_file: str | None,
    instructions: str | None,
    instructions_file: str | None,
) -> Config:
    config = load_config()
    resolved_profile = _resolve_profile_override(
        default_profile=config.profile,
        profile=profile,
        profile_file=profile_file,
        instructions=instructions,
        instructions_file=instructions_file,
    )
    return config.model_copy(update={"profile": resolved_profile})


def _resolve_profile_override(
    *,
    default_profile: AgentProfile,
    profile: str | None,
    profile_file: str | None,
    instructions: str | None,
    instructions_file: str | None,
) -> AgentProfile:
    resolved = default_profile
    if profile_file is not None:
        profile_path = Path(profile_file)
        try:
            resolved = load_profile_from_toml(profile_path)
        except OSError as exc:
            raise ValueError(f"Failed to read profile file: {profile_path}") from exc
    elif profile is not None:
        resolved = _resolve_builtin_profile(profile)

    instructions_override = _load_instructions_override(
        instructions=instructions,
        instructions_file=instructions_file,
    )
    if instructions_override is not None:
        resolved = replace(resolved, instructions=instructions_override)

    if not resolved.instructions.strip():
        raise ValueError("Active profile instructions must be non-empty.")
    return resolved


def _resolve_builtin_profile(name: str) -> AgentProfile:
    try:
        return BUILTIN_PROFILES[name]
    except KeyError as exc:
        known = ", ".join(sorted(BUILTIN_PROFILES.keys()))
        raise ValueError(f"Unknown profile '{name}'. Known profiles: {known}") from exc


def _load_instructions_override(
    *, instructions: str | None, instructions_file: str | None
) -> str | None:
    if instructions is not None:
        if not instructions.strip():
            raise ValueError("Instructions override must be non-empty.")
        return instructions
    if instructions_file is None:
        return None

    path = Path(instructions_file)
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read instructions file: {path}") from exc
    if not value.strip():
        raise ValueError("Instructions file must contain non-empty content.")
    return value


def _emit_protocol_event(event: ProtocolEvent) -> None:
    sys.stdout.write(f"{event.model_dump_json()}\n")


def _render_error_message(exc: Exception) -> str:
    return str(exc).strip() or type(exc).__name__


async def _resolve_resume_rollout_path(*, config: Config, resume: str) -> Path:
    path_candidate = await asyncio.to_thread(lambda: Path(resume).expanduser())
    if await asyncio.to_thread(path_candidate.exists):
        return path_candidate

    sessions_root = _resolve_sessions_root(config)
    latest = resolve_latest_rollout(resume, root=sessions_root)
    if latest is not None:
        return latest

    legacy_path = sessions_root / f"{resume}.json"
    if await asyncio.to_thread(legacy_path.exists):
        return await import_legacy_session_json(
            legacy_path=legacy_path,
            thread_id=resume,
            sessions_root=sessions_root,
        )

    raise RolloutReplayError(
        code="rollout_not_found",
        message=f"Unable to resolve rollout for {resume!r}.",
    )


async def _run_prompt_json(
    prompt: str,
    *,
    approval_policy: ApprovalPolicy,
    sandbox_policy: SandboxPolicy,
    dump_llm_request: bool = False,
    profile: str | None = None,
    profile_file: str | None = None,
    instructions: str | None = None,
    instructions_file: str | None = None,
    resume: str | None = None,
) -> int:
    config, session, model_client, tool_router = await _build_runtime(
        approval_policy=approval_policy,
        sandbox_policy=sandbox_policy,
        dump_llm_request=dump_llm_request,
        profile=profile,
        profile_file=profile_file,
        instructions=instructions,
        instructions_file=instructions_file,
        resume=resume,
    )
    adapter = EventAdapter(thread_id=session.thread_id)

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
    except KeyboardInterrupt:
        _emit_protocol_event(adapter.turn_failed(INTERRUPTED_ERROR))
        return INTERRUPTED_EXIT_CODE
    except asyncio.CancelledError:
        _emit_protocol_event(adapter.turn_failed(INTERRUPTED_ERROR))
        return INTERRUPTED_EXIT_CODE
    except RolloutReplayError as exc:
        _emit_protocol_event(adapter.turn_failed(f"{exc.code}: {exc.message}"))
        return 1
    except Exception as exc:
        _emit_protocol_event(adapter.turn_failed(exc))
        return 1
    finally:
        await session.close_rollout()
    return 0


async def _run_tui_mode(
    *,
    approval_policy: ApprovalPolicy,
    sandbox_policy: SandboxPolicy,
    dump_llm_request: bool = False,
    profile: str | None = None,
    profile_file: str | None = None,
    instructions: str | None = None,
    instructions_file: str | None = None,
    resume: str | None = None,
) -> int:
    config = _resolve_runtime_config(
        profile=profile,
        profile_file=profile_file,
        instructions=instructions,
        instructions_file=instructions_file,
    )
    session = await _build_session(config=config, resume=resume)
    model_client = _build_model_client(config, dump_llm_request=dump_llm_request)
    bridge: TuiBridge | None = None

    async def _tui_ask_user_fn(tool: Any, args: dict[str, Any]) -> ReviewDecision:
        if bridge is None:
            raise RuntimeError(
                "TUI bridge was not initialised before approval callback was invoked."
            )
        return await bridge.request_approval(tool, args)

    tool_router = _build_tool_router(
        approval_policy=approval_policy,
        sandbox_policy=sandbox_policy,
        ask_user_fn=_tui_ask_user_fn,
    )
    bridge = TuiBridge(
        session=session,
        model_client=model_client,
        tool_router=tool_router,
        cwd=config.cwd,
    )
    await bridge.run()
    await session.close_rollout()
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


def _has_profile_cli_overrides(args: argparse.Namespace) -> bool:
    return any(
        value is not None
        for value in (
            args.profile,
            args.profile_file,
            args.instructions,
            args.instructions_file,
        )
    )


def _resolve_effective_policies(
    *,
    approval_flag: str | None,
    sandbox_flag: str | None,
    config: Config,
) -> tuple[ApprovalPolicy, SandboxPolicy]:
    approval_policy = (
        ApprovalPolicy(approval_flag)
        if approval_flag is not None
        else config.default_approval_policy
    )
    sandbox_policy = (
        SandboxPolicy(sandbox_flag) if sandbox_flag is not None else config.default_sandbox_policy
    )
    return approval_policy, sandbox_policy


def _emit_interrupted_stderr() -> None:
    print(f"[ERROR] {INTERRUPTED_ERROR}", file=sys.stderr)


def _run_session_command(
    *,
    args: argparse.Namespace,
    config: Config,
) -> int:
    if len(args.prompt_tail) == 0:
        print("[ERROR] Missing session subcommand. Expected one of: list, read, archive, unarchive", file=sys.stderr)
        return 1

    subcommand = args.prompt_tail[0]
    sessions_root = _resolve_sessions_root(config)
    archived_root = _resolve_archived_sessions_root(config)
    if subcommand == "list":
        return _session_list(sessions_root=sessions_root)
    if subcommand == "read":
        if len(args.prompt_tail) < 2:
            print("[ERROR] session read requires an id", file=sys.stderr)
            return 1
        return _session_read(
            session_id=args.prompt_tail[1],
            sessions_root=sessions_root,
            archived_root=archived_root,
        )
    if subcommand == "archive":
        if len(args.prompt_tail) < 2:
            print("[ERROR] session archive requires an id", file=sys.stderr)
            return 1
        return _session_move(
            session_id=args.prompt_tail[1],
            source_root=sessions_root,
            dest_root=archived_root,
            action="archive",
        )
    if subcommand == "unarchive":
        if len(args.prompt_tail) < 2:
            print("[ERROR] session unarchive requires an id", file=sys.stderr)
            return 1
        return _session_move(
            session_id=args.prompt_tail[1],
            source_root=archived_root,
            dest_root=sessions_root,
            action="unarchive",
        )

    print(
        f"[ERROR] Unknown session subcommand {subcommand!r}. Expected one of: list, read, archive, unarchive",
        file=sys.stderr,
    )
    return 1


def _session_list(*, sessions_root: Path) -> int:
    rollout_paths = sorted(sessions_root.glob("rollout-*.jsonl"), key=lambda p: p.name, reverse=True)
    for path in rollout_paths:
        state = replay_rollout(path)
        token_total = state.cumulative_usage["input_tokens"] + state.cumulative_usage["output_tokens"]
        date_token = _rollout_date_token(path.name)
        print(
            f"{state.thread_id}\t{date_token}\tturns={state.turn_count}\ttokens={token_total}\tstatus={state.status}"
        )
    return 0


def _session_read(*, session_id: str, sessions_root: Path, archived_root: Path) -> int:
    path = _resolve_session_path(
        session_id=session_id,
        active_root=sessions_root,
        archived_root=archived_root,
    )
    state = replay_rollout(path)
    if state.session_closed is not None:
        token_total = {
            "input_tokens": state.session_closed.token_total.input_tokens,
            "output_tokens": state.session_closed.token_total.output_tokens,
        }
        turn_count = state.session_closed.turn_count
        last_user_message = state.session_closed.last_user_message
    else:
        token_total = dict(state.cumulative_usage)
        turn_count = state.turn_count
        last_user_message = _last_user_message_from_history(state.history)

    print(
        json.dumps(
            {
                "thread_id": state.thread_id,
                "status": state.status,
                "turn_count": turn_count,
                "token_total": token_total,
                "last_user_message": last_user_message,
            },
            ensure_ascii=True,
        )
    )
    return 0


def _session_move(
    *,
    session_id: str,
    source_root: Path,
    dest_root: Path,
    action: str,
) -> int:
    source_path = _resolve_session_path(session_id=session_id, active_root=source_root, archived_root=None)
    _ensure_directory(dest_root)
    dest_path = dest_root / source_path.name
    if dest_path.exists():
        raise RolloutReplayError(
            code="replay_failure",
            message=f"Cannot {action} session {session_id!r}; destination already exists.",
        )
    shutil.move(str(source_path), str(dest_path))
    return 0


def _resolve_session_path(
    *,
    session_id: str,
    active_root: Path,
    archived_root: Path | None,
) -> Path:
    candidate = Path(session_id).expanduser()
    if candidate.exists():
        return candidate

    resolved = resolve_latest_rollout(session_id, root=active_root)
    if resolved is not None:
        return resolved
    if archived_root is not None:
        archived = resolve_latest_rollout(session_id, root=archived_root)
        if archived is not None:
            return archived
    raise RolloutReplayError(
        code="rollout_not_found",
        message=f"Session {session_id!r} not found.",
    )


def _last_user_message_from_history(history: Sequence[object]) -> str | None:
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content
    return None


def _rollout_date_token(filename: str) -> str:
    prefix = "rollout-"
    if not filename.startswith(prefix):
        return "unknown"
    remainder = filename[len(prefix) :]
    return remainder.split("-", 1)[0]


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
    try:
        default_config = load_config()
        approval_policy, sandbox_policy = _resolve_effective_policies(
            approval_flag=args.approval,
            sandbox_flag=args.sandbox,
            config=default_config,
        )
    except Exception as exc:
        message = _render_error_message(exc)
        print(f"[ERROR] {message}", file=sys.stderr)
        return 1
    if args.tui_mode:
        if args.json:
            parser.error("--json cannot be used with --tui-mode")
        if args.prompt is not None:
            parser.error("prompt is not accepted with --tui-mode")
        if args.prompt_tail:
            parser.error("extra arguments are not accepted with --tui-mode")
        try:
            tui_kwargs: dict[str, Any] = {
                "approval_policy": approval_policy,
                "sandbox_policy": sandbox_policy,
            }
            if args.dump_llm_request:
                tui_kwargs["dump_llm_request"] = True
            if _has_profile_cli_overrides(args):
                tui_kwargs.update(
                    {
                        "profile": args.profile,
                        "profile_file": args.profile_file,
                        "instructions": args.instructions,
                        "instructions_file": args.instructions_file,
                    }
                )
            if args.resume is not None:
                tui_kwargs["resume"] = args.resume
            return asyncio.run(_run_tui_mode(**tui_kwargs))
        except KeyboardInterrupt:
            _emit_interrupted_stderr()
            return INTERRUPTED_EXIT_CODE
        except Exception as exc:
            message = _render_error_message(exc)
            print(f"[ERROR] {message}", file=sys.stderr)
            return 1

    if args.prompt == "session":
        if args.json:
            parser.error("--json cannot be used with session commands")
        if args.resume is not None:
            parser.error("--resume cannot be used with session commands")
        try:
            return _run_session_command(args=args, config=default_config)
        except RolloutReplayError as exc:
            print(f"[ERROR] {exc.code}: {exc.message}", file=sys.stderr)
            return 1

    if args.prompt_tail:
        parser.error(f"unrecognized arguments: {' '.join(args.prompt_tail)}")
    if args.prompt is None:
        parser.error("the following arguments are required: prompt")
    prompt: str = args.prompt

    if args.json:
        try:
            json_kwargs: dict[str, Any] = {
                "prompt": prompt,
                "approval_policy": approval_policy,
                "sandbox_policy": sandbox_policy,
            }
            if args.dump_llm_request:
                json_kwargs["dump_llm_request"] = True
            if _has_profile_cli_overrides(args):
                json_kwargs.update(
                    {
                        "profile": args.profile,
                        "profile_file": args.profile_file,
                        "instructions": args.instructions,
                        "instructions_file": args.instructions_file,
                    }
                )
            if args.resume is not None:
                json_kwargs["resume"] = args.resume
            return asyncio.run(_run_prompt_json(**json_kwargs))
        except KeyboardInterrupt:
            return INTERRUPTED_EXIT_CODE
        except RolloutReplayError as exc:
            print(f"[ERROR] {exc.code}: {exc.message}", file=sys.stderr)
            return 1
        except Exception as exc:
            message = _render_error_message(exc)
            print(f"[ERROR] {message}", file=sys.stderr)
            return 1

    try:
        prompt_kwargs: dict[str, Any] = {
            "prompt": prompt,
            "approval_policy": approval_policy,
            "sandbox_policy": sandbox_policy,
        }
        if args.dump_llm_request:
            prompt_kwargs["dump_llm_request"] = True
        if _has_profile_cli_overrides(args):
            prompt_kwargs.update(
                {
                    "profile": args.profile,
                    "profile_file": args.profile_file,
                    "instructions": args.instructions,
                    "instructions_file": args.instructions_file,
                }
            )
        if args.resume is not None:
            prompt_kwargs["resume"] = args.resume
        final_text = asyncio.run(_run_prompt(**prompt_kwargs))
    except KeyboardInterrupt:
        _emit_interrupted_stderr()
        return INTERRUPTED_EXIT_CODE
    except RolloutReplayError as exc:
        print(f"[ERROR] {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        message = _render_error_message(exc)
        print(f"[ERROR] {message}", file=sys.stderr)
        return 1
    print(final_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
