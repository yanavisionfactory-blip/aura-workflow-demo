const UNAVAILABLE_STATUSES = new Set([
  "blocked",
  "failed",
  "cancelled",
]);

export function planningConnectionRequirements(run = {}) {
  if (run.status !== "waiting_for_action") return [];
  const result = run.result || {};
  const blocker = run.blocker || {};
  const values = [
    ...(Array.isArray(result.missing_capabilities) ? result.missing_capabilities : []),
    blocker.code === "connection_required" ? blocker.tool_slug : null,
  ]
    .map((value) => String(value || "").trim())
    .filter(Boolean);
  return [...new Set(values)];
}

// Planning is only a proposal stage. A runtime blocker must remain an inline,
// retryable planning error; it must never manufacture an executable fallback.
export function planningDisposition(run = {}) {
  if (run.status === "awaiting_approval" && run.plan?.steps?.length) {
    return "review";
  }
  if (
    run.status === "waiting_for_action"
    && (
      run.result?.status === "waiting_for_connection"
      || run.blocker?.code === "connection_required"
      || planningConnectionRequirements(run).length > 0
    )
  ) {
    return "connection";
  }
  if (run.status === "waiting_for_action") return "unavailable";
  if (UNAVAILABLE_STATUSES.has(run.status)) return "unavailable";
  return "wait";
}
