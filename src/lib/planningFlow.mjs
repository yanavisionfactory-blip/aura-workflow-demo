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
    ...(Array.isArray(run.connection_requirements)
      ? run.connection_requirements
        .filter((item) => item?.status !== "satisfied")
        .map((item) => item.canonical_provider || item.provider_hint || item.capability)
      : []),
    ...(Array.isArray(result.missing_capabilities) ? result.missing_capabilities : []),
    blocker.code === "connection_required" ? blocker.tool_slug : null,
  ]
    .map((value) => String(value || "").trim())
    .filter(Boolean);
  return [...new Set(values)];
}

const PROMPT_TOOL_ALIASES = {
  "meta-ads": ["meta ads", "facebook ads", "meta advertising"],
};

const normalizedWords = (value) => String(value || "")
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, " ")
  .trim();

export function shouldStartFreshPlanningRun({
  nextIntent = "",
  activeIntent = "",
  hasActiveRequest = false,
  revisionInstruction = "",
} = {}) {
  if (!hasActiveRequest) return false;
  if (String(revisionInstruction || "").trim()) return true;
  return normalizedWords(nextIntent) !== normalizedWords(activeIntent);
}

export function promptConnectionRequirements(prompt = "", catalog = [], connections = {}) {
  const text = ` ${normalizedWords(prompt)} `;
  if (!text.trim()) return [];
  return catalog
    .filter((tool) => {
      if (!tool?.name || connections[tool.name]) return false;
      const slug = normalizedWords(tool.slug || tool.name);
      const aliases = [
        normalizedWords(tool.name),
        slug,
        ...(PROMPT_TOOL_ALIASES[slug.replace(/ /g, "-")] || []),
      ];
      return aliases.some((alias) => alias && text.includes(` ${normalizedWords(alias)} `));
    })
    .map((tool) => tool.slug || tool.name);
}

export function planningConnectionsEnabled(compileState = "") {
  return compileState !== "validating";
}

export function publicPlanningFailure(error = {}) {
  const status = Number(error?.status || 0);
  const message = String(error?.message || "").toLowerCase();

  if (status === 401 || status === 403) {
    return "Your AURA session needs a quick refresh. Sign in again, then retry.";
  }
  if (
    !status
    && (
      message.includes("failed to fetch")
      || message.includes("networkerror")
      || message.includes("network request failed")
      || error?.name === "AbortError"
    )
  ) {
    return "AURA is reconnecting to the planning service. Nothing ran; retry in a moment.";
  }
  if (status === 429) {
    return "AURA is briefly busy. Nothing ran; retry in a moment.";
  }
  if (status >= 500 || message.includes("timed out") || message.includes("timeout")) {
    return "AURA hit a temporary service interruption. Nothing ran; retry in a moment.";
  }
  return "AURA couldn't prepare this workflow yet. Nothing ran; retry in a moment.";
}

// Planning is only a proposal stage. A runtime blocker must remain an inline,
// retryable planning error; it must never manufacture an executable fallback.
export function planningDisposition(run = {}) {
  // The backend owns technical recovery.  Its public projection takes
  // precedence over the internal persistence status (which may be blocked or
  // failed while an incident is quarantined backstage).
  if (run.public_status === "recovering") return "wait";
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

const ACTIVE_PLANNING_STATUSES = new Set(["queued", "planning", "recovering"]);

export function planningRecoveryGraceEligible(run = {}) {
  return planningDisposition(run) === "wait"
    && (
      run.public_status === "recovering"
      || ACTIVE_PLANNING_STATUSES.has(run.status)
    );
}

export function approvalStartFailure(run = {}, error = {}) {
  const stillAtReview = run.status === "awaiting_approval"
    && run.blocker?.code === "plan_approval_required"
    && Boolean(run.plan?.steps?.length);
  if (!stillAtReview) return null;
  return {
    message: error?.message || "AURA couldn't validate this plan for execution. Review it and try again.",
    status: error?.status || null,
  };
}
