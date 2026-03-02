const DEFAULT_APPROVAL_POLICY = "on-request";
const DEFAULT_SANDBOX_POLICY = "danger-full-access";
const TRUE_VALUES = new Set(["1", "true", "yes", "on"]);
const APPROVAL_POLICIES = ["never", "on-failure", "on-request", "unless-trusted"] as const;
const SANDBOX_POLICIES = ["danger-full-access", "read-only", "workspace-write"] as const;

export type ApprovalPolicyValue = (typeof APPROVAL_POLICIES)[number];
export type SandboxPolicyValue = (typeof SANDBOX_POLICIES)[number];

export function resolveApprovalPolicy(
  env: NodeJS.ProcessEnv = process.env,
): ApprovalPolicyValue {
  const rawPolicy = env.PYCODEX_TUI_APPROVAL ?? DEFAULT_APPROVAL_POLICY;
  return APPROVAL_POLICIES.includes(rawPolicy as ApprovalPolicyValue)
    ? (rawPolicy as ApprovalPolicyValue)
    : "on-request";
}

export function resolveSandboxPolicy(
  env: NodeJS.ProcessEnv = process.env,
): SandboxPolicyValue {
  const rawPolicy = env.PYCODEX_TUI_SANDBOX ?? DEFAULT_SANDBOX_POLICY;
  return SANDBOX_POLICIES.includes(rawPolicy as SandboxPolicyValue)
    ? (rawPolicy as SandboxPolicyValue)
    : "danger-full-access";
}

export function buildPycodexArgs(
  env: NodeJS.ProcessEnv = process.env,
): string[] {
  const approvalPolicy = resolveApprovalPolicy(env);
  const sandboxPolicy = resolveSandboxPolicy(env);
  const args = [
    "-m",
    "pycodex",
    "--tui-mode",
    "--approval",
    approvalPolicy,
    "--sandbox",
    sandboxPolicy,
  ];
  if (isTuiLlmRequestDumpEnabled(env)) {
    args.push("--dump-llm-request");
  }
  return args;
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

export function isTuiLlmRequestDumpEnabled(
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const raw = env.PYCODEX_TUI_DUMP_LLM_REQUEST;
  if (raw === undefined) {
    return false;
  }
  return TRUE_VALUES.has(raw.trim().toLowerCase());
}
