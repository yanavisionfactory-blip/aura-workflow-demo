const UNAVAILABLE_STATUSES = new Set([
  "waiting_for_action",
  "blocked",
  "failed",
  "cancelled",
]);

// Planning is only a proposal stage. A runtime blocker must remain an inline,
// retryable planning error; it must never manufacture an executable fallback.
export function planningDisposition(run = {}) {
  if (run.status === "awaiting_approval" && run.plan?.steps?.length) {
    return "review";
  }
  if (UNAVAILABLE_STATUSES.has(run.status)) return "unavailable";
  return "wait";
}
