# pycodex/approval — Module Rules

Applies in addition to root `AGENTS.md`. Root rules take precedence when they conflict.

## Approval Policy
- Approval logic must be stateless except through `ApprovalStore` — no module-level mutable state.
- `ApprovalStore` cache keys must be deterministic and stable across process restarts (serialize tool name + normalized args).
- `APPROVED_FOR_SESSION` decisions are cached for the lifetime of the store instance; `APPROVED` decisions are not cached.

## Orchestrator
- The orchestrator is the only place where approval, sandbox, and execution are wired together.
- Read-only tools bypass the approval check entirely — do not prompt for read-only operations.
- The `ask_user_fn` callback is injected at construction; never hardcode `input()` calls in orchestrator or policy code.

## Testing
- Never bypass approval checks in tests by passing `policy=NEVER` silently.
- Use a mock `ask_user_fn` that returns a predetermined `ReviewDecision` — this makes approval behavior explicit and testable.
- Test both the cached path (`APPROVED_FOR_SESSION` hit) and the uncached path (prompt required).

## Sandboxing
- Sandbox enforcement is additive to approval — a command that passes approval can still be blocked by the sandbox.
- Sandbox failures on `ON_FAILURE` policy must prompt the user to escalate, not silently succeed.
