export function hasDurablePlan(runId, backendPlan) {
  return Boolean(runId && backendPlan?.steps?.length);
}

// Late reads of a previous selection must not replace a fresh user intent.
export function shouldRestoreRememberedRun({ rememberedRunId, currentRememberedRunId,
  startedAtGeneration, currentGeneration, hasCurrentIntent = false } = {}) {
  return Boolean(rememberedRunId) && rememberedRunId === currentRememberedRunId
    && startedAtGeneration === currentGeneration && !hasCurrentIntent;
}

// These values prefill the normal input only. They carry no run, account,
// approval or execution state and must never dispatch a provider operation.
export function workflowInputPrompt({ state, search = "" } = {}) {
  const candidate = typeof state?.workflowPrompt === "string"
    ? state.workflowPrompt : new URLSearchParams(search).get("prompt") || "";
  return candidate.trim() && candidate.length <= 20000 ? candidate : "";
}

export function savedRunActionLocation(prompt) {
  return { pathname: "/", state: { newWorkflow: true,
    workflowPrompt: typeof prompt === "string" && prompt.length <= 20000 ? prompt : "" } };
}

// Rebuild only the bounded campaign recipe from its reviewed source inputs.
// Upload handles are transient; saved arguments retain the source fingerprint
// and literal export rows. This is a new proposal, never an execution receipt
// or a transfer of the previous run's approval.
export function campaignRepeatPrompt(prompt, steps = []) {
  const prefix = "AURA_CAMPAIGN_REPORT_V1\n";
  if (!String(prompt || "").startsWith(prefix) || !Array.isArray(steps)
      || steps.length !== 1 || steps[0]?.operation !== "sheets.campaign_report.create") return null;
  const fields = steps[0].arguments;
  if (!fields || !/^[a-f0-9]{64}$/.test(fields.source_sha256 || "")
      || !["google_ads", "meta_ads", "ga4"].every((key) =>
        Array.isArray(fields[key]) && fields[key].length >= 2 && fields[key].length <= 100)) return null;
  const required = ["client_name", "data_status", "currency", "prior_start", "prior_end",
    "current_start", "current_end", "meta_attribution", "ga4_attribution", "source_filename"];
  if (!required.every((key) => typeof fields[key] === "string" && fields[key].trim())) return null;
  const keys = [...required, "google_attribution", "source_timezone", "source_sha256",
    "google_ads", "meta_ads", "ga4"];
  const next = prefix + JSON.stringify(Object.fromEntries(keys
    .filter((key) => fields[key] !== undefined).map((key) => [key, fields[key]])));
  return next.length <= 20000 ? next : null;
}

export function restorablePlanningRun(run = {}) {
  if (run.plan_approved) return false;
  if (run.status === "awaiting_approval") return Boolean(run.plan?.steps?.length);
  if (run.status !== "waiting_for_action") return false;
  return run.result?.status === "waiting_for_connection"
    || run.blocker?.code === "connection_required"
    || (run.connection_requirements || []).some((item) => item.status !== "satisfied");
}

export function savedRunResumeView(run = {}) {
  if (!run?.id) return null;
  if (!run.plan_approved) {
    if (restorablePlanningRun(run)) return "plan";
    if (["queued", "planning", "recovering"].includes(run.status)
      || run.blocker?.code === "planning_retry_required"
      || run.public_status === "recovering") return "plan";
    return null;
  }
  if (!run.plan?.steps?.length) return null;
  if (run.automation_state?.status === "blocked"
      || ["waiting_for_action", "blocked", "failed"].includes(run.status)) return "recovery";
  if (run.status === "awaiting_approval" && run.steps?.some((step) =>
    step.approval_status === "pending" && step.approval_preview?.status === "ready"
  )) return "preview";
  if (["queued", "running", "recovering", "awaiting_approval", "completed"].includes(run.status)) return "execution";
  return null;
}

export function sameExecutablePlan(before = [], after = []) {
  const identity = (steps) => steps.map((step) => ({
    tool_slug: step.tool_slug || step.tool,
    operation: step.operation,
    arguments: step.arguments,
    reason: step.reason || step.action,
    expected_output: step.expected_output || step.output,
    depends_on: step.depends_on || [],
  }));
  return JSON.stringify(identity(before)) === JSON.stringify(identity(after));
}

export function unmatchedWriteTools(visibleSteps = [], executableSteps = [], toolName = (step) => step.tool) {
  const visibleWrites = visibleSteps
    .filter((step) => step.riskLevel === "modify"
      && String(step.tool || "").trim().toLowerCase() !== "aura intelligence")
    .map((step) => String(step.tool || "").trim());
  const executableWrites = executableSteps
    .filter((step) => step.consequential)
    .map((step) => String(toolName(step) || "").trim())
    .filter(Boolean);
  const visibleNames = new Set(visibleWrites.map((tool) => tool.toLowerCase()));
  const executableNames = new Set(executableWrites.map((tool) => tool.toLowerCase()));
  return [...new Set([
    ...executableWrites.filter((tool) => !visibleNames.has(tool.toLowerCase())),
    ...visibleWrites.filter((tool) => !executableNames.has(tool.toLowerCase())),
  ])];
}

export function planningRequestPrompt(confirmedIntent, revisionInstruction = "", reviewedSteps = []) {
  const intent = String(confirmedIntent || "").trim();
  const revision = String(revisionInstruction || "").trim();
  if (!revision) return intent;
  const steps = Array.isArray(reviewedSteps) ? reviewedSteps.map((step, index) => ({
    position: index + 1,
    key: step.key,
    tool: step.tool_slug || step.toolSlug || step.tool,
    operation: step.operation,
    title: step.title,
    action: step.action || step.reason,
    expected_output: step.output || step.expected_output,
    arguments: step.arguments,
    depends_on: step.depends_on,
  })) : [];
  const current = steps.length ? `\nCurrent reviewed steps (preserve unchanged steps and dependencies): ${JSON.stringify(steps)}` : "";
  return `${intent}\n\nThe user reviewed the proposed workflow and requested this change: ${revision}${current}\nReturn the complete revised executable plan. Apply the change exactly; do not repeat the previous plan unchanged.`;
}
