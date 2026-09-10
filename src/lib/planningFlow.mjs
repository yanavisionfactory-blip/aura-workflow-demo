const FALLBACK_STATUSES = new Set([
  "waiting_for_action",
  "blocked",
  "failed",
  "cancelled",
]);

// Planning is only a proposal stage. A runtime blocker must never replace the
// editable plan UI before the user has reviewed or started anything.
export function planningDisposition(run = {}) {
  if (run.status === "awaiting_approval" && run.plan?.steps?.length) {
    return "review";
  }
  if (FALLBACK_STATUSES.has(run.status)) return "fallback";
  return "wait";
}
