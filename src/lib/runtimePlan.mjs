export function hasDurablePlan(runId, backendPlan) {
  return Boolean(runId && backendPlan?.steps?.length);
}

export function restorablePlanningRun(run = {}) {
  if (run.plan_approved) return false;
  if (run.status === "awaiting_approval") return Boolean(run.plan?.steps?.length);
  if (run.status !== "waiting_for_action") return false;
  return run.result?.status === "waiting_for_connection"
    || run.blocker?.code === "connection_required"
    || (run.connection_requirements || []).some((item) => item.status !== "satisfied");
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

export function planningRequestPrompt(confirmedIntent, revisionInstruction = "", reviewedSteps = []) {
  const intent = String(confirmedIntent || "").trim();
  const revision = String(revisionInstruction || "").trim();
  if (!revision) return intent;
  const steps = Array.isArray(reviewedSteps) ? reviewedSteps.map((step, index) => ({
    position: index + 1,
    key: step.key,
    tool: step.tool || step.tool_slug,
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
