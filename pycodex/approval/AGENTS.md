# pycodex/approval — Module Rules

Applies in addition to root `AGENTS.md`. Root rules take precedence when they conflict.

## Approval Policy
- Approval logic must be stateless except through `ApprovalStore` — no module-level mutable state.
- `ApprovalStore` cache keys must be deterministic and order-independent (`json.dumps(..., sort_keys=True, ensure_ascii=True)` via store normalization).
- `APPROVED_FOR_SESSION` decisions are cached for the lifetime of the store instance; `APPROVED` decisions are not cached.
- Approval key strategy is tool-aware:
  - default key fallback is `{"tool": tool.name, "args": args}`
  - `write_file` uses resolved absolute path
  - `shell` uses conservative canonicalization (wrapper-equivalent forms collapse; semantically sensitive inline forms stay distinct)

## Orchestrator
- The orchestrator is the only place where approval, sandbox, and execution are wired together.
- Read-only tools bypass the approval check entirely — do not prompt for read-only operations.
- The `ask_user_fn` callback is injected at construction; never hardcode `input()` calls in orchestrator or policy code.
- `ABORT` must raise `ToolAborted` and terminate the active turn; do not convert abort into a normal denied/error continuation path.
- Concurrent calls with the same approval key must share one in-flight prompt via `ApprovalStore` pending-prompt coordination.

## Testing
- Never bypass approval checks in tests by passing `policy=NEVER` silently.
- Use a mock `ask_user_fn` that returns a predetermined `ReviewDecision` — this makes approval behavior explicit and testable.
- Test both the cached path (`APPROVED_FOR_SESSION` hit) and the uncached path (prompt required).
- Include deterministic regression tests for:
  - abort terminal-turn behavior
  - tool-specific approval-key behavior and canonicalization boundaries

## Sandboxing
- Sandbox enforcement is additive to approval — a command that passes approval can still be blocked by the sandbox.
- Sandbox failures on `ON_FAILURE` policy must prompt the user to escalate, not silently succeed.
