export function hasDurablePlan(runId, backendPlan) {
  return Boolean(runId && backendPlan?.steps?.length);
}

export function planningRequestPrompt(confirmedIntent, revisionInstruction = "") {
  const intent = String(confirmedIntent || "").trim();
  const revision = String(revisionInstruction || "").trim();
  if (!revision) return intent;
  return `${intent}\n\nThe user reviewed the proposed workflow and requested this change: ${revision}`;
}
