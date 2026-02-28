import { spawn } from "node:child_process";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { render } from "ink";
import * as React from "react";

import { App } from "./app.js";
import { StdioReader, StdioWriter } from "./protocol/transports/stdio.js";
import { buildPycodexArgs } from "./runtime/launch.js";

const SHUTDOWN_TIMEOUT_MS = 5000;

function resolveRepoRoot(): string {
  const dirname = path.dirname(fileURLToPath(import.meta.url));
  return path.resolve(dirname, "..", "..", "..");
}

function isMainModule(): boolean {
  const entryPath = process.argv[1];
  if (entryPath === undefined) {
    return false;
  }
  const modulePath = fileURLToPath(import.meta.url);
  return path.resolve(entryPath) === modulePath;
}

function main(): void {
  const repoRoot = resolveRepoRoot();
  const pythonCommand = process.env.PYCODEX_PYTHON ?? "python3";
  const child = spawn(pythonCommand, buildPycodexArgs(), {
    cwd: repoRoot,
    env: process.env,
    stdio: ["pipe", "pipe", "pipe"],
  });

  const reader = new StdioReader(child);
  const writer = new StdioWriter(child);

  reader.start();

  let shutdownRequested = false;
  let didUnmount = false;
  let forceKillTimer: NodeJS.Timeout | null = null;
  let overrideExitCode: number | null = null;

  // app is assigned below after render(); unmountOnce guards against it being
  // called before assignment by checking didUnmount first.
  // eslint-disable-next-line prefer-const
  let app: ReturnType<typeof render>;

  function unmountOnce(): void {
    if (didUnmount) {
      return;
    }
    didUnmount = true;
    app.unmount();
  }

  function requestShutdown(options?: { interrupt?: boolean; exitCode?: number }): void {
    if (options?.exitCode !== undefined) {
      overrideExitCode = options.exitCode;
    }

    if (options?.interrupt === true) {
      writer.sendInterrupt();
    }

    if (shutdownRequested) {
      return;
    }

    shutdownRequested = true;
    writer.close();

    if (child.exitCode === null) {
      child.kill("SIGTERM");
      forceKillTimer = setTimeout(() => {
        if (child.exitCode === null) {
          child.kill("SIGKILL");
        }
      }, SHUTDOWN_TIMEOUT_MS);
      forceKillTimer.unref();
      return;
    }

    unmountOnce();
    process.exit(overrideExitCode ?? child.exitCode);
  }

  // Register signal handlers before render() so no SIGINT can slip through
  // during the Ink initialisation window.
  process.once("SIGINT", () => {
    requestShutdown({ interrupt: true });
  });

  process.once("SIGTERM", () => {
    requestShutdown();
  });

  child.once("error", (error) => {
    process.stderr.write(`[tui] child process error: ${error.message}\n`);
    requestShutdown({ exitCode: 1 });
  });

  child.once("exit", (code) => {
    if (forceKillTimer !== null) {
      clearTimeout(forceKillTimer);
      forceKillTimer = null;
    }

    unmountOnce();
    process.exit(overrideExitCode ?? code ?? 0);
  });

  reader.onClose(() => {
    requestShutdown();
  });

  app = render(React.createElement(App, { reader, writer }), {
    exitOnCtrlC: false,
  });
}

if (isMainModule()) {
  main();
}
