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

Run in watch mode:

```bash
npm run dev
```

Build:

```bash
npm run build
```

Run built output:

```bash
npm run start
```

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
