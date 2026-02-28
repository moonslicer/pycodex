const DEFAULT_APPROVAL_POLICY = "on-request";
const TRUE_VALUES = new Set(["1", "true", "yes", "on"]);

export function buildPycodexArgs(
  env: NodeJS.ProcessEnv = process.env,
): string[] {
  const approvalPolicy = env.PYCODEX_TUI_APPROVAL ?? DEFAULT_APPROVAL_POLICY;
  return ["-m", "pycodex", "--tui-mode", "--approval", approvalPolicy];
}

export function isTuiDebugEnabled(
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const raw = env.PYCODEX_TUI_DEBUG;
  if (raw === undefined) {
    return false;
  }
  return TRUE_VALUES.has(raw.trim().toLowerCase());
}
