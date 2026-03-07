# TUI Guide

This directory contains the terminal UI built with React + Ink. Python remains the runtime brain; the TUI is a typed protocol client.

## Architecture at a Glance

- `src/index.ts`: process wiring, child process lifecycle, startup/shutdown.
- `src/app.tsx`: UI composition and hook orchestration.
- `src/components/`: presentational terminal components.
- `src/hooks/`: deterministic state transitions and event-to-state mapping.
- `src/protocol/`: typed protocol contracts and stdio reader/writer boundary.
- `src/runtime/`: launch helpers.

## Local Development

Install deps:

```bash
npm install
```

Run for interactive local use:

```bash
npm run dev
```

Run in watch mode (for TUI code iteration):

```bash
npm run dev:watch
```

`dev:watch` can restart the process while typing because it is a file-watcher wrapper.
Use `npm run dev` or `npm run start` for normal interactive chatting.

Build:

```bash
npm run build
```

Run built output:

```bash
npm run start
```

## LLM Request Dump Debugging

To inspect the exact payload pycodex sends to the LLM from TUI mode, enable:

```bash
PYCODEX_TUI_DUMP_LLM_REQUEST=1 npm run start \
  2> >(tee -a /tmp/pycodex-tui-llm.log >&2)
```

This prints `[llm-request] ...` lines to stderr (not into the chat transcript).

If you also set `PYCODEX_FAKE_MODEL=1`, no real LLM request is sent, so no
request dump entries will be produced.

## Quality Commands

- `npm run typecheck`
- `npm run lint`
- `npm test`

For most TUI changes, run all three.

## Contract Notes

- Keep protocol event/command shapes centralized in `src/protocol/types.ts`.
- Parse/serialize JSON only at transport boundaries.
- Unknown or malformed protocol messages must be ignored safely, not crash the UI.
- When protocol contracts change in Python, update TUI protocol types and tests in the same change.
