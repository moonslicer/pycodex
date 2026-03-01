import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import * as path from "node:path";

import { render } from "ink";
import * as React from "react";

import { App } from "./app.js";
import { StdioReader, StdioWriter } from "./protocol/transports/stdio.js";
import type { ProtocolReader } from "./protocol/reader.js";
import type { ProtocolWriter } from "./protocol/writer.js";
import {
  buildPycodexArgs,
  isTuiDebugEnabled,
  resolveApprovalPolicy,
} from "./runtime/launch.js";

const SHUTDOWN_TIMEOUT_MS = 5000;

function resolveRepoRoot(argv: readonly string[] = process.argv): string {
  const entryPath = argv[1];
  if (entryPath === undefined) {
    return process.cwd();
  }

  const resolvedEntryPath = path.resolve(entryPath);
  let current = path.dirname(resolvedEntryPath);
  while (path.basename(current) !== "tui") {
    const parent = path.dirname(current);
    if (parent === current) {
      return process.cwd();
    }
    current = parent;
  }

  return path.dirname(current);
}

function isMainModule(argv: readonly string[] = process.argv): boolean {
  const entryPath = argv[1];
  if (entryPath === undefined) {
    return false;
  }

  return isSupportedEntrypointPath(path.resolve(entryPath));
}

export function isSupportedEntrypointPath(normalizedPath: string): boolean {
  return (
    normalizedPath.endsWith(`${path.sep}dist${path.sep}src${path.sep}index.js`) ||
    normalizedPath.endsWith(`${path.sep}dist${path.sep}index.js`) ||
    normalizedPath.endsWith(`${path.sep}src${path.sep}index.ts`)
  );
}

type ProcessRef = {
  argv: string[];
  env: NodeJS.ProcessEnv;
  once: (signal: "SIGINT" | "SIGTERM", listener: () => void) => void;
  exit: (code?: number) => void;
  stderr: {
    write: (message: string) => unknown;
  };
};

type RenderApp = (
  reader: ProtocolReader,
  writer: ProtocolWriter,
  handlers: {
    approvalPolicy: "never" | "on-failure" | "on-request" | "unless-trusted";
    debug: boolean;
    onExitRequested: () => void;
  },
) => {
  unmount: () => void;
};

type MainDependencies = {
  resolveRepoRoot: (argv: readonly string[]) => string;
  spawnProcess: (
    command: string,
    args: readonly string[],
    options: {
      cwd: string;
      env: NodeJS.ProcessEnv;
      stdio: ["pipe", "pipe", "pipe"];
    },
  ) => ChildProcess;
  buildPycodexArgs: (env?: NodeJS.ProcessEnv) => string[];
  makeReader: (child: ChildProcess) => ProtocolReader;
  makeWriter: (child: ChildProcess) => ProtocolWriter;
  renderApp: RenderApp;
  processRef: ProcessRef;
  setTimeoutRef: typeof setTimeout;
  clearTimeoutRef: typeof clearTimeout;
};

const DEFAULT_MAIN_DEPENDENCIES: MainDependencies = {
  resolveRepoRoot,
  spawnProcess: spawn,
  buildPycodexArgs,
  makeReader: (child: ChildProcess) => new StdioReader(child),
  makeWriter: (child: ChildProcess) => new StdioWriter(child),
  renderApp: (reader, writer, handlers) =>
    render(React.createElement(App, { ...handlers, reader, writer }), {
      exitOnCtrlC: false,
    }),
  processRef: {
    argv: process.argv,
    env: process.env,
    once: (signal, listener) => {
      process.once(signal, listener);
    },
    exit: (code?: number) => {
      process.exit(code);
    },
    stderr: process.stderr,
  },
  setTimeoutRef: setTimeout,
  clearTimeoutRef: clearTimeout,
};

export function main(dependencies: Partial<MainDependencies> = {}): void {
  const deps: MainDependencies = {
    ...DEFAULT_MAIN_DEPENDENCIES,
    ...dependencies,
  };

  const repoRoot = deps.resolveRepoRoot(deps.processRef.argv);
  const pythonCommand = deps.processRef.env.PYCODEX_PYTHON ?? "python3";
  const child = deps.spawnProcess(
    pythonCommand,
    deps.buildPycodexArgs(deps.processRef.env),
    {
      cwd: repoRoot,
      env: deps.processRef.env,
      stdio: ["pipe", "pipe", "pipe"],
    },
  );

  const reader = deps.makeReader(child);
  const writer = deps.makeWriter(child);
  const debug = isTuiDebugEnabled(deps.processRef.env);
  const approvalPolicy = resolveApprovalPolicy(deps.processRef.env);

  reader.start();

  let shutdownRequested = false;
  let interruptRequested = false;
  let didUnmount = false;
  let didExit = false;
  let forceKillTimer: ReturnType<typeof setTimeout> | null = null;
  let overrideExitCode: number | null = null;
  let appHandle: { unmount: () => void } | null = null;

  function unmountOnce(): void {
    if (didUnmount || appHandle === null) {
      return;
    }
    didUnmount = true;
    appHandle.unmount();
  }

  function clearForceKillTimer(): void {
    if (forceKillTimer === null) {
      return;
    }

    deps.clearTimeoutRef(forceKillTimer);
    forceKillTimer = null;
  }

  function exitOnce(code: number | null | undefined): void {
    if (didExit) {
      return;
    }

    didExit = true;
    clearForceKillTimer();
    unmountOnce();
    deps.processRef.exit(overrideExitCode ?? code ?? 0);
  }

  function requestShutdown(options?: { interrupt?: boolean; exitCode?: number }): void {
    if (options?.exitCode !== undefined) {
      overrideExitCode = options.exitCode;
    }

    if (options?.interrupt === true && !interruptRequested) {
      interruptRequested = true;
      writer.sendInterrupt();
    }

    if (shutdownRequested) {
      return;
    }

    shutdownRequested = true;
    writer.close();

    if (child.exitCode === null) {
      child.kill("SIGTERM");
      forceKillTimer = deps.setTimeoutRef(() => {
        if (child.exitCode === null) {
          child.kill("SIGKILL");
        }
      }, SHUTDOWN_TIMEOUT_MS);
      if (typeof forceKillTimer.unref === "function") {
        forceKillTimer.unref();
      }
      return;
    }

    exitOnce(child.exitCode);
  }

  function didExitBeforeRender(): boolean {
    return didExit;
  }

  // Register signal handlers before render() so no SIGINT can slip through
  // during the Ink initialisation window.
  deps.processRef.once("SIGINT", () => {
    requestShutdown({ interrupt: true });
  });

  deps.processRef.once("SIGTERM", () => {
    requestShutdown();
  });

  child.once("error", (error) => {
    deps.processRef.stderr.write(`[tui] child process error: ${error.message}\n`);
    requestShutdown({ exitCode: 1 });
  });

  child.once("exit", (code) => {
    exitOnce(code);
  });

  reader.onClose(() => {
    requestShutdown();
  });

  appHandle = deps.renderApp(reader, writer, {
    approvalPolicy,
    debug,
    onExitRequested: () => {
      requestShutdown();
    },
  });
  if (didExitBeforeRender()) {
    unmountOnce();
  }
}

if (isMainModule(process.argv)) {
  main();
}
