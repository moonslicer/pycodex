const DEFAULT_APPROVAL_POLICY = "on-request";
const TRUE_VALUES = new Set(["1", "true", "yes", "on"]);
const APPROVAL_POLICIES = ["never", "on-failure", "on-request", "unless-trusted"] as const;

export type ApprovalPolicyValue = (typeof APPROVAL_POLICIES)[number];

export function resolveApprovalPolicy(
  env: NodeJS.ProcessEnv = process.env,
): ApprovalPolicyValue {
  const rawPolicy = env.PYCODEX_TUI_APPROVAL ?? DEFAULT_APPROVAL_POLICY;
  return APPROVAL_POLICIES.includes(rawPolicy as ApprovalPolicyValue)
    ? (rawPolicy as ApprovalPolicyValue)
    : "on-request";
}

export function buildPycodexArgs(
  env: NodeJS.ProcessEnv = process.env,
): string[] {
  const approvalPolicy = resolveApprovalPolicy(env);
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
