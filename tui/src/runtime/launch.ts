const DEFAULT_APPROVAL_POLICY = "on-request";

export function buildPycodexArgs(
  env: NodeJS.ProcessEnv = process.env,
): string[] {
  const approvalPolicy = env.PYCODEX_TUI_APPROVAL ?? DEFAULT_APPROVAL_POLICY;
  return ["-m", "pycodex", "--tui-mode", "--approval", approvalPolicy];
}
