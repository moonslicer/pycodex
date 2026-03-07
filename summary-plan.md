# Intelligent Compaction Engineering Plan

## Background

Milestone 7 shipped a working compaction pipeline with `ThresholdV1Strategy` (ratio-based
trigger) and `LocalSummaryV1Implementation` (syntactic one-liner formatter). Milestone 8
shipped append-only JSONL rollout persistence with `compaction.applied` records and full
`--resume` support.

This plan upgrades compaction to match the quality bar set by Claude Code and codex-rs:

1. **Model-generated summaries** — replace the syntactic formatter with a structured,
   model-written summary that captures intent, code changes, errors, and next steps.
2. **Compact boundary tracking** — incremental compaction: only summarize new content
   since the last compaction, leaving prior summaries intact.
3. **API token count as trigger** — use actual `input_tokens` from API responses as the
   primary trigger signal instead of the `chars/4` heuristic.
4. **Fix replay of compaction** — the `compaction.applied` record must mutate history
   during replay so resumed sessions reflect post-compaction state correctly.

---

## Reference Implementations

**Claude Code** (`~/.nvm/.../claude-code/cli.js`):
- Sends the **full conversation** (all roles, tool_use, tool_result) to the model.
- Binary content (images, documents) inside tool_results is replaced with `[image]` /
  `[document]` placeholders; all other content passes through unmodified.
- Uses a 9-section structured prompt with an analysis step before writing `<summary>`.
- Tracks `compact_boundary` markers so subsequent compactions only re-summarize new
  content after the last boundary.
- Trigger: `contextWindow - maxOutputTokens - 13_000 (safety buffer)` using actual API
  token counts, not estimates.

**codex-rs** (`codex-rs/core/src/compact.rs`):
- Non-OpenAI path: calls the model with a summarization prompt, collects the last
  assistant message as the summary, rebuilds history as
  `[selected_user_messages_up_to_20k_tokens, summary_message]`.
- OpenAI path: delegates to the API's native compact endpoint.
- Always re-injects fresh initial context (AGENTS.md, env) after compaction.

---

## Architecture After This Plan

```
Agent.run_turn()  [async]
  └─ await _compact_history_if_needed()   [now async]
        └─ CompactionOrchestrator.compact(session)  [now async]
              ├─ ThresholdV1Strategy.plan(context)   [sync, boundary-aware]
              │     reads session._total_input_tokens as primary token estimate
              │     detects last [compaction.summary.v1] block → partial range
              ├─ await ModelSummaryV1Implementation.summarize(request)  [async]
              │     formats full transcript (user/assistant/tool_use/tool_result)
              │     replaces binary blobs with [image]/[document] placeholders
              │     calls ModelClient.complete() with structured 9-section prompt
              │     parses <summary>...</summary> from response
              └─ session.replace_range_with_system_summary(start, end, text)
                    replaces history[start:end] with one summary system message
                    leaves history[0:start] (prior summaries) intact

Rollout persistence:
  compaction.applied record gains replace_start field (default 0, backward-compat)
  replay: _apply_rollout_item applies replace_start/replace_end mutation to history
```

---

## What Exists Today (Do Not Break)

| File | Relevant state |
|---|---|
| `pycodex/core/compaction.py` | `ThresholdV1Strategy`, `LocalSummaryV1Implementation`, `CompactionOrchestrator`, `STRATEGY_REGISTRY`, `IMPLEMENTATION_REGISTRY`, `create_compaction_orchestrator()` |
| `pycodex/core/session.py` | `replace_prefix_with_system_summary(replace_count, summary_text)` — full-prefix replacement only |
| `pycodex/core/agent.py` | `_compact_history_if_needed()` (sync), `_resolve_compaction_orchestrator()`, `_persist_compaction()` |
| `pycodex/core/model_client.py` | `ModelClient.stream()` async generator — streaming only, no single-response path |
| `pycodex/core/rollout_schema.py` | `CompactionApplied` — no `replace_start` field |
| `pycodex/core/rollout_replay.py` | `_apply_rollout_item` ignores `compaction.applied` records |
| `pycodex/core/config.py` | `compaction_strategy`, `compaction_implementation`, `compaction_threshold_ratio`, `compaction_context_window_tokens`, `compaction_options` |

---

## Locked Contracts (must remain stable after this work)

- `[compaction.summary.v1]` block marker string must not change — it is the boundary
  detection key used by both the strategy and `_is_summary_block_item()`.
- `STRATEGY_REGISTRY` and `IMPLEMENTATION_REGISTRY` must remain pluggable by name.
- `local_summary_v1` must continue to work unchanged — it is the default for offline/test
  environments where no model client is available.
- `schema_version: "1.0"` on rollout records. New fields must be optional with defaults.
- `CompactionStrategy.plan()` remains synchronous (no I/O, pure logic).
- `RolloutReplayError` error codes (`rollout_not_found`, `schema_version_mismatch`,
  `replay_failure`) must not change.

---

## In-Scope Files

```
pycodex/core/compaction.py            — primary changes (async protocol, new impl, boundary)
pycodex/core/model_client.py          — add ModelClient.complete() single-response path
pycodex/core/session.py               — add replace_range_with_system_summary()
pycodex/core/agent.py                 — make _compact_history_if_needed() async
pycodex/core/rollout_schema.py        — add replace_start to CompactionApplied
pycodex/core/rollout_replay.py        — apply compaction.applied mutation during replay
pycodex/core/config.py                — add compaction_custom_instructions field

tests/core/test_compaction.py         — extend with async tests, boundary tests
tests/core/test_compaction_registry.py — extend with model_summary_v1 registration
tests/core/test_model_client.py       — add complete() unit tests
tests/core/test_rollout_schema.py     — add replace_start field tests
tests/core/test_rollout_replay.py     — add compaction mutation replay tests
tests/core/test_token_usage.py        — add API-count trigger path tests
```

---

## Task Breakdown

---

### T1 — Add `ModelClient.complete()` single-response path

**File:** `pycodex/core/model_client.py`

The existing `ModelClient.stream()` is an async generator. Summarization needs a single
blocking response, not a stream. Add a `complete()` coroutine that collects the full text
from a stream and returns it.

**Implementation:**

```python
async def complete(
    self,
    messages: list[PromptItem],
    *,
    instructions: str = "",
    max_output_tokens: int = 4096,
) -> str:
    """Collect full model text response (no tools, no streaming)."""
    text_parts: list[str] = []
    async for event in self.stream(messages, tools=[], instructions=instructions):
        if isinstance(event, OutputTextDelta):
            text_parts.append(event.delta)
    return "".join(text_parts)
```

Notes:
- Pass `tools=[]` — summarization must never invoke tools (matches Claude Code's
  `IMPORTANT: Do NOT use any tools` instruction).
- `max_output_tokens` is currently not wired into `_stream_once` request kwargs.
  Add it to the `create_kwargs` dict in `_stream_once` when non-zero, so callers
  can cap summary length.
- The retry behavior in `stream()` already handles transient failures.

**Tests:** `tests/core/test_model_client.py`
- `complete()` joins text deltas in order.
- `complete()` returns empty string when no `OutputTextDelta` events are emitted.
- `complete()` passes `tools=[]` regardless of config tools.

**Verify:**
```
.venv/bin/pytest tests/core/test_model_client.py -k complete -q
```

---

### T2 — Make compaction protocol async

**File:** `pycodex/core/compaction.py`

`CompactionImplementation.summarize()` is currently synchronous. `ModelSummaryV1Implementation`
must be async because it calls `ModelClient.complete()`. Change the protocol and all
implementations.

**Changes to `compaction.py`:**

1. Change `CompactionImplementation` Protocol:
   ```python
   class CompactionImplementation(Protocol):
       name: str
       async def summarize(self, request: SummaryRequest) -> SummaryOutput: ...
   ```

2. Change `LocalSummaryV1Implementation.summarize()` to `async def summarize()` — body
   is unchanged, just add `async`. The method does no I/O so this is a safe no-op change.

3. Change `CompactionOrchestrator.compact()` to `async def compact()`:
   ```python
   async def compact(self, session: Session) -> CompactionApplied | None:
       ...
       summary_output = await self.implementation.summarize(request)
       ...
   ```

4. Change `SupportsCompactionOrchestrator` Protocol:
   ```python
   class SupportsCompactionOrchestrator(Protocol):
       async def compact(self, session: Session) -> CompactionApplied | None: ...
   ```

**File:** `pycodex/core/agent.py`

Change `_compact_history_if_needed()` to async and update the call site:

```python
async def _compact_history_if_needed(self) -> CompactionApplied | None:
    orchestrator = self._resolve_compaction_orchestrator()
    if orchestrator is None:
        return None
    return await orchestrator.compact(self.session)
```

In `run_turn()`, change `compaction = self._compact_history_if_needed()` to
`compaction = await self._compact_history_if_needed()`.

**Tests:** Update all existing sync compaction tests to use `asyncio.run()` or
`pytest.mark.asyncio`. No behavior changes.

**Verify:**
```
.venv/bin/pytest tests/core/test_compaction.py tests/core/test_compaction_registry.py -q
```

---

### T3 — Add `replace_range_with_system_summary()` to `Session`

**File:** `pycodex/core/session.py`

The existing `replace_prefix_with_system_summary(replace_count, summary_text)` always
replaces from index 0. Partial compaction needs to replace an arbitrary
`history[start:end]` slice while leaving `history[0:start]` (prior summaries) intact.

**Add new method:**

```python
def replace_range_with_system_summary(
    self,
    *,
    replace_start: int,
    replace_end: int,
    summary_text: str,
) -> bool:
    """Replace history[replace_start:replace_end] with one system summary message."""
    if replace_start < 0 or replace_end <= replace_start:
        return False
    effective_end = min(replace_end, len(self._history))
    if effective_end <= replace_start:
        return False
    self._history = [
        *self._history[:replace_start],
        {"role": "system", "content": summary_text},
        *self._history[effective_end:],
    ]
    return True
```

Keep `replace_prefix_with_system_summary()` unchanged — it delegates to this new method
with `replace_start=0`:
```python
def replace_prefix_with_system_summary(self, *, replace_count: int, summary_text: str) -> bool:
    return self.replace_range_with_system_summary(
        replace_start=0,
        replace_end=replace_count,
        summary_text=summary_text,
    )
```

**Tests:** `tests/core/test_compaction.py` (or a dedicated session test)
- `replace_range_with_system_summary` replaces middle slice, leaves prefix intact.
- Returns `False` when `replace_start >= replace_end`.
- Returns `False` when range is entirely out of bounds.
- Prior summaries in `history[0:replace_start]` are not modified.

---

### T4 — Compact boundary tracking in `ThresholdV1Strategy`

**File:** `pycodex/core/compaction.py`

The strategy currently always plans `replace_end = len(history) - keep_recent_items`
with an implicit `replace_start = 0`. When a `[compaction.summary.v1]` block already
exists in history, the strategy should only compact items after it.

**Changes to `CompactionPlan`:**

Add `replace_start` field:
```python
@dataclass(frozen=True, slots=True)
class CompactionPlan:
    replace_start: int          # new — default 0 for full compaction
    replace_end: int
    used_tokens: int
    remaining_ratio: float
    threshold_ratio: float
```

**Changes to `ThresholdV1Strategy.plan()`:**

After computing `replace_end`, scan history for the last summary block:

```python
# Find boundary: last existing [compaction.summary.v1] block
replace_start = 0
for i, item in enumerate(context.history):
    if _is_summary_block_item(item):
        replace_start = i + 1  # compact items AFTER the summary, not the summary itself

# Items available to compact
compactable_count = replace_end - replace_start
if compactable_count < self.min_replace_items:
    return None  # not enough new content since last compaction

return CompactionPlan(
    replace_start=replace_start,
    replace_end=replace_end,
    used_tokens=used_tokens,
    remaining_ratio=remaining_ratio,
    threshold_ratio=self.threshold_ratio,
)
```

**Changes to `CompactionOrchestrator.compact()`:**

Use `plan.replace_start` and `plan.replace_end`:
```python
items_to_replace = history[plan.replace_start : plan.replace_end]
summary_items = _summary_source_items(items_to_replace)
...
replaced = session.replace_range_with_system_summary(
    replace_start=plan.replace_start,
    replace_end=plan.replace_end,
    summary_text=summary_text,
)
```

Update the internal `CompactionResult` dataclass in `compaction.py` to carry `replace_start`.
(This is the return type of `CompactionOrchestrator.compact()`, distinct from the Pydantic
`CompactionApplied` rollout schema model in `rollout_schema.py` updated in T7.)

```python
@dataclass(frozen=True, slots=True)
class CompactionResult:
    strategy: str
    implementation: str
    replace_start: int          # new
    replace_end: int
    replaced_items: int
    ...
```

Rename all usages of the internal `CompactionApplied` dataclass in `compaction.py` to
`CompactionResult` to eliminate the name collision with `rollout_schema.CompactionApplied`.

**Tests:**
- First compaction: `replace_start=0`, full prefix is replaced.
- Second compaction: `replace_start` points to item after existing summary block.
- If new content since last compaction is fewer than `min_replace_items`, plan returns `None`.
- History before `replace_start` (prior summaries) is unchanged after second compaction.
- `CompactionOrchestrator.compact()` returns a `CompactionResult` (not `CompactionApplied`);
  `Agent._persist_compaction()` maps it to a `rollout_schema.CompactionApplied` record.

---

### T5 — `ModelSummaryV1Implementation`

**File:** `pycodex/core/compaction.py`

This is the main deliverable. Calls the model with a structured prompt to generate a
semantic summary. The implementation receives a `ModelClient` at construction time.

**Summary prompt** (adapt from Claude Code's `y6Y` prompt):

```
Your task is to create a detailed summary of the conversation so far. This summary
will replace the compacted history — another model instance will resume the session
using only this summary plus recent context.

Be thorough with technical details, code patterns, and decisions that are essential
for continuing the work without losing context.

Your summary MUST include these sections:

1. Primary Request and Intent
   Capture all of the user's explicit requests and goals in detail.

2. Key Technical Concepts
   List important technologies, frameworks, and architectural decisions discussed.

3. Files and Code Sections
   For each file read, edited, or created: what changed and why. Include code
   snippets for non-obvious changes.

4. Tool Calls and Outcomes
   Summarize significant shell commands run, their purpose, and their output (truncate
   long outputs to the key result).

5. Errors and Fixes
   List errors encountered and how they were resolved. Include any user corrections.

6. All User Messages
   List every user message verbatim (not tool results). Critical for preserving intent.

7. Pending Tasks
   Any tasks explicitly requested but not yet completed.

8. Current Work
   Precisely what was being done immediately before this summary. Include filenames
   and code snippets.

9. Next Step
   The single next action to take, directly quoting the most recent user instruction.
   Only include if clearly defined — do not invent next steps.

Wrap your reasoning in <analysis> tags first. Then output ONLY the summary inside
<summary>...</summary> tags. Do not use any tools.
```

**Transcript formatting** (what gets sent as the conversation to summarize):

The `SummaryRequest.items` list contains `PromptItem` dicts. Format each as readable
text before sending to the model. Rules:
- `role: user` → `User: <content>`
- `role: assistant` → `Assistant: <content>`
- `role: system` → omit (initial context / prior summaries are noise for the summarizer)
- `type: function_call` → `Tool call: <name>(<arguments>)` — include name and arguments
- `role: tool` → `Tool result [<call_id>]: <content>` — include full output, but
  replace any base64 blobs (content starting with `data:image/` or long base64 strings)
  with `[binary data omitted]`. Cap individual tool result at 2000 chars with
  `[...truncated]` to avoid bloating the summarization prompt.

**Implementation:**

```python
@dataclass(slots=True)
class ModelSummaryV1Implementation:
    model_client: SupportsModelComplete   # Protocol: async complete(messages, ...) -> str
    custom_instructions: str = ""
    max_output_tokens: int = 4096
    name: str = "model_summary_v1"

    async def summarize(self, request: SummaryRequest) -> SummaryOutput:
        transcript = _format_transcript_for_summary(request.items)
        prompt = _build_model_summary_prompt(
            transcript=transcript,
            custom_instructions=self.custom_instructions,
        )
        messages: list[PromptItem] = [{"role": "user", "content": prompt}]
        raw = await self.model_client.complete(
            messages,
            instructions="",
            max_output_tokens=self.max_output_tokens,
        )
        text = _extract_summary_block(raw)
        if not text:
            # Fallback: use raw response if parsing fails
            text = raw.strip() or "No summary generated."
        if len(text) > request.max_chars:
            text = text[: request.max_chars] + "..."
        return SummaryOutput(text=text)
```

`_extract_summary_block(raw)` finds the last `<summary>` ... `</summary>` span in the
response. Return the content between the tags, stripped.

`_format_transcript_for_summary(items)` produces a readable string:
```python
def _format_transcript_for_summary(items: list[PromptItem]) -> str:
    lines: list[str] = []
    for item in items:
        if _is_summary_block_item(item):
            # Prior summary: include it so the model knows what was already compacted
            lines.append(f"[Prior compaction summary]\n{item.get('content', '')}")
            continue
        role = item.get("role")
        item_type = item.get("type")
        if item_type == "function_call":
            name = item.get("name", "unknown")
            args = _truncate(str(item.get("arguments", "{}")), max_chars=500)
            lines.append(f"Tool call: {name}({args})")
        elif role == "tool":
            call_id = item.get("tool_call_id", "")
            content = str(item.get("content", ""))
            content = _sanitize_tool_output(content)    # replace base64, cap length
            lines.append(f"Tool result [{call_id}]: {content}")
        elif role == "user":
            lines.append(f"User: {item.get('content', '')}")
        elif role == "assistant":
            lines.append(f"Assistant: {item.get('content', '')}")
        # non-summary system messages (initial context injected at session start) are omitted;
        # summary system messages are handled above by the _is_summary_block_item branch.
    return "\n\n".join(lines)
```

`_sanitize_tool_output(text)`:
- Replace `data:image/[^;]+;base64,[A-Za-z0-9+/=]{20,}` with `[binary data omitted]`.
- Cap at 2000 chars, append `[...truncated]` if cut.

**Protocol for injection:**

Define a lightweight protocol so `ModelSummaryV1Implementation` is testable without a
real `ModelClient`:

```python
class SupportsModelComplete(Protocol):
    async def complete(
        self,
        messages: list[PromptItem],
        *,
        instructions: str = "",
        max_output_tokens: int = 4096,
    ) -> str: ...
```

`ModelClient` already satisfies this after T1.

**Registry and factory:**

```python
# In IMPLEMENTATION_REGISTRY, model_summary_v1 requires a model_client at build time.
# create_compaction_orchestrator gains an optional model_client parameter:

def create_compaction_orchestrator(
    *,
    strategy_name: str = DEFAULT_COMPACTION_STRATEGY,
    implementation_name: str = DEFAULT_COMPACTION_IMPLEMENTATION,
    strategy_options: dict[str, object] | None = None,
    implementation_options: dict[str, object] | None = None,
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS,
    summary_max_chars: int = DEFAULT_SUMMARY_MAX_CHARS,
    model_client: SupportsModelComplete | None = None,   # new
) -> CompactionOrchestrator:
```

The `ValueError` guard lives inside the factory function itself (not in
`create_compaction_orchestrator`), so the registry is self-enforcing:

```python
def _build_model_summary_v1_implementation(
    options: dict[str, object],
    model_client: SupportsModelComplete | None,   # matches ImplementationFactory signature
) -> CompactionImplementation:
    if model_client is None:
        raise ValueError(
            "model_summary_v1 requires a model_client; "
            "pass model_client= to create_compaction_orchestrator()"
        )
    return ModelSummaryV1Implementation(
        model_client=model_client,
        custom_instructions=str(options.get("custom_instructions", "")),
        max_output_tokens=_to_int_option(options, "max_output_tokens", 4096),
    )
```

**Wire model_client in `Agent._resolve_compaction_orchestrator()`:**

```python
self.compaction_orchestrator = create_compaction_orchestrator(
    ...
    model_client=self.model_client,   # agent already holds a model_client
)
```

**Tests:** `tests/core/test_compaction.py`
- Inject a fake `SupportsModelComplete` returning `<summary>Test summary.</summary>`.
- Verify `SummaryOutput.text` equals `"Test summary."`.
- Verify model receives user message containing the formatted transcript.
- Verify tool calls appear as `Tool call: name(args)` in transcript.
- Verify tool results appear as `Tool result [id]: output` in transcript.
- Verify prior `[compaction.summary.v1]` blocks appear as `[Prior compaction summary]`.
- Verify system messages (non-summary) are omitted from transcript.
- Verify base64 blobs in tool outputs are replaced with `[binary data omitted]`.
- Verify tool outputs longer than 2000 chars are truncated.
- Verify fallback when response contains no `<summary>` tags.
- Verify `max_chars` truncation applied to extracted summary.

**Verify:**
```
.venv/bin/pytest tests/core/test_compaction.py -k model_summary -q
```

---

### T6 — API token count as primary trigger

**File:** `pycodex/core/compaction.py`, `pycodex/core/agent.py`

`ThresholdV1Strategy` computes `used_tokens` via `_estimate_prompt_tokens(history)` which
is `total_chars / 4`. The session already tracks `_total_input_tokens` accumulated from
API responses. Use that as the primary signal.

**Changes to `CompactionContext`:**

Add an optional field:
```python
@dataclass(frozen=True, slots=True)
class CompactionContext:
    history: list[PromptItem]
    prompt_tokens_estimate: int        # existing: char-based estimate
    context_window_tokens: int
    api_input_tokens: int = 0          # new: cumulative from API responses
```

**Changes to `Session`** (if not already present):

Add `cumulative_usage() -> dict[str, int]` to `session.py` returning at minimum
`{"input_tokens": self._total_input_tokens}`. This is a new public method — add it to the
In-Scope Files list (`pycodex/core/session.py`).

**Changes to `CompactionOrchestrator.compact()`:**

```python
async def compact(self, session: Session) -> CompactionResult | None:
    history = session.to_prompt()
    cumulative = session.cumulative_usage()
    api_tokens = cumulative["input_tokens"]
    char_estimate = _estimate_prompt_tokens(history)
    # Prefer API count when available (non-zero means at least one turn completed)
    prompt_tokens_estimate = api_tokens if api_tokens > 0 else char_estimate
    context = CompactionContext(
        history=history,
        prompt_tokens_estimate=prompt_tokens_estimate,
        context_window_tokens=self.context_window_tokens,
        api_input_tokens=api_tokens,
    )
    ...
```

`ThresholdV1Strategy.plan()` already uses `context.prompt_tokens_estimate` — no change
required there once the orchestrator populates it correctly.

**Changes to `Config`:**

Add `compaction_custom_instructions`:
```python
compaction_custom_instructions: str = ""
```

Wire it in `_load_env_config()`:
```python
if value := os.getenv("PYCODEX_COMPACTION_CUSTOM_INSTRUCTIONS"):
    env["compaction_custom_instructions"] = value
```

Pass it through in `Agent._resolve_compaction_orchestrator()`:
```python
implementation_options.setdefault(
    "custom_instructions", config.compaction_custom_instructions
)
```

**Tests:** `tests/core/test_token_usage.py`
- When `session._total_input_tokens > 0`, orchestrator uses that value as
  `prompt_tokens_estimate`, not the char estimate.
- When session has no completed turns (`_total_input_tokens == 0`), falls back to
  char estimate.

---

### T7 — Fix `compaction.applied` replay mutation

**File:** `pycodex/core/rollout_schema.py`

Add `replace_start` to `CompactionApplied` with default `0` for backward compatibility:

```python
class CompactionApplied(_FrozenModel):
    schema_version: Literal["1.0"]
    type: Literal["compaction.applied"] = "compaction.applied"
    thread_id: str
    summary_text: str
    replace_start: StrictInt = 0        # new — default 0 for full-prefix compaction
    replace_end: StrictInt
    replaced_items: StrictInt
    strategy: str
    implementation: str
    strategy_options: dict[str, Any]
    implementation_options: dict[str, Any]
```

**File:** `pycodex/core/rollout_replay.py`

Change `_apply_rollout_item` to apply the compaction mutation during replay:

```python
elif item_type == "compaction.applied":
    compaction_record = cast(CompactionApplied, item)
    replace_start = int(compaction_record.replace_start)
    replace_end = int(compaction_record.replace_end)
    effective_end = min(replace_end, len(history))
    if effective_end > replace_start >= 0:
        summary_item: PromptItem = {
            "role": "system",
            "content": compaction_record.summary_text,
        }
        del history[replace_start:effective_end]
        history.insert(replace_start, summary_item)
    else:
        state_warnings.append(
            f"compaction.applied record has invalid range "
            f"[{replace_start}:{replace_end}] for history length {len(history)}"
        )
```

**Why this was wrong before:** The `history.item` records persisted after a compaction
are only the NEW items appended to history post-compaction (model responses, tool calls).
The summary block itself and the retained recent items are not re-persisted as
`history.item` records. Without replaying the `compaction.applied` mutation, a resumed
session would contain all the original pre-compaction items PLUS the new post-compaction
items — effectively un-doing the compaction in memory.

**File:** `pycodex/core/agent.py`, `_persist_compaction()`

Pass `replace_start` in the rollout record:
```python
RolloutCompactionApplied(
    ...
    replace_start=compaction.replace_start,    # new
    replace_end=compaction.replace_end,
    ...
)
```

**Tests:** `tests/core/test_rollout_replay.py`
- Replay with `compaction.applied` record correctly replaces `history[start:end]` with
  summary block.
- History items before `replace_start` remain intact (partial compaction case).
- History items written after compaction append correctly after the summary block.
- `replace_start=0` (old records) behaves identically to the prior full-prefix behavior.
- Out-of-range `replace_end` is clamped, warning emitted.
- Two consecutive `compaction.applied` records both apply correctly.

**Verify:**
```
.venv/bin/pytest tests/core/test_rollout_replay.py -k compaction -q
```

---

### T8 — Integration and quality gates

**Update `IMPLEMENTATION_REGISTRY`** to include `model_summary_v1`. Because this
implementation requires a `model_client`, the registry value must carry a sentinel or
the `_build_*` function signature must accept an optional `model_client` parameter.

Cleanest approach: extend the registry type to allow factories that accept a
`model_client` argument:

```python
ImplementationFactory: TypeAlias = Callable[
    [dict[str, object], SupportsModelComplete | None],
    CompactionImplementation,
]

IMPLEMENTATION_REGISTRY: dict[str, ImplementationFactory] = {
    "local_summary_v1": lambda opts, _client: _build_local_summary_v1_implementation(opts),
    "model_summary_v1": _build_model_summary_v1_implementation,
}
```

Update `create_compaction_orchestrator()` to pass `model_client` to the factory.

**Test coverage additions:**

- `tests/core/test_compaction_registry.py`: `model_summary_v1` is registered; raises
  `ValueError` when `model_client=None` is passed.
- `tests/core/test_compaction.py`: full orchestrator integration test with fake model
  client returning a valid `<summary>` response; verifies partial compaction (second
  pass leaves prior summary intact); verifies `CompactionApplied.replace_start` is set.

**Run full gates:**
```
.venv/bin/ruff check . --fix
.venv/bin/ruff format .
.venv/bin/mypy --strict pycodex/
.venv/bin/pytest tests/ -v
```

---

## Task Dependency Graph

```
T1 (ModelClient.complete)
  └─> T5 (ModelSummaryV1Implementation)
        └─> T8 (integration + gates)

T2 (async protocol)
  └─> T5
  └─> T8

T3 (replace_range_with_system_summary)
  └─> T4 (boundary tracking)
        └─> T5
        └─> T8

T6 (API token count trigger)
  └─> T8

T7 (replay mutation fix)
  └─> T8
```

T1, T2, T3, T6, T7 are independent and can be worked in parallel.
T4 requires T3. T5 requires T1, T2, T4. T8 requires all.

---

## Config Reference After This Plan

| Key | Default | Env var | Description |
|---|---|---|---|
| `compaction_strategy` | `threshold_v1` | `PYCODEX_COMPACTION_STRATEGY` | Strategy name |
| `compaction_implementation` | `local_summary_v1` | `PYCODEX_COMPACTION_IMPLEMENTATION` | Implementation name |
| `compaction_threshold_ratio` | `0.2` | `PYCODEX_COMPACTION_THRESHOLD_RATIO` | Remaining context ratio that triggers compaction |
| `compaction_context_window_tokens` | `128_000` | `PYCODEX_COMPACTION_CONTEXT_WINDOW_TOKENS` | Model context window size |
| `compaction_custom_instructions` | `""` | `PYCODEX_COMPACTION_CUSTOM_INSTRUCTIONS` | Appended to summary prompt (e.g. "focus on Python changes") |
| `compaction_options.strategy.*` | (varies) | — | Per-strategy options (threshold_ratio, keep_recent_items, min_replace_items) |
| `compaction_options.implementation.*` | (varies) | — | Per-impl options (max_lines, max_output_tokens, custom_instructions) |

Example `pycodex.toml` to enable model-generated summaries:
```toml
compaction_implementation = "model_summary_v1"
compaction_custom_instructions = "Focus on Python code changes and test output."
compaction_threshold_ratio = 0.15

[compaction_options.implementation]
max_output_tokens = 4096
```

---

## Manual Verification

After all tasks pass quality gates, verify end-to-end:

```bash
# 1. Run a multi-turn session with model_summary_v1 until compaction triggers
PYCODEX_COMPACTION_IMPLEMENTATION=model_summary_v1 \
PYCODEX_COMPACTION_THRESHOLD_RATIO=0.01 \
  .venv/bin/python -m pycodex "run a loop of 20 tasks and report progress each step"

# 2. Confirm compaction.applied in rollout file
cat ~/.pycodex/sessions/rollout-*.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    r = json.loads(line)
    if r.get('type') == 'compaction.applied':
        print('strategy:', r['strategy'])
        print('implementation:', r['implementation'])
        print('replace_start:', r.get('replace_start', 0))
        print('replace_end:', r['replace_end'])
        print('summary_text[:200]:', r['summary_text'][:200])
"

# 3. Resume and confirm state is correct
THREAD_ID=<thread-id-from-above>
.venv/bin/python -m pycodex --resume $THREAD_ID "what were you working on?"
# Expected: model should describe the prior session work from the summary

# 4. Confirm partial compaction on second compact trigger
# (run another long session after resume and confirm second compaction only
#  summarizes new content; prior summary block is preserved at history[0])
```

---

## Out of Scope

- Anthropic API native compaction (`compact-2026-01-12` beta) — future `AnthropicRemoteSummaryImplementation`.
- OpenAI native `compact_conversation_history` endpoint — future `OpenAIRemoteSummaryImplementation`.
- Compaction in TUI (only applies to the Python agent core, TUI observes `context_compacted` events already).
- Changing the `[compaction.summary.v1]` block marker format.
- SQLite index of rollout files (was already out-of-scope for M8).
