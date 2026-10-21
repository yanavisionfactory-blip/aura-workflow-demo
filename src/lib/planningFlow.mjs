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

export function skippedToolRevision(toolName) {
  return `Do not call ${toolName}. Preserve the original requested deliverables and constraints. `
    + "Keep drafts that can be prepared from authorized inputs or public sources the user permits; "
    + "a channel mentioned in draft copy does not require an authenticated channel connection. "
    + "Remove provider calls and references to unavailable provider outputs, not independently "
    + "supportable content or public booking links. Explicitly report account checks that were not "
    + "performed and any outcomes that still require this tool. Never invent verification, assets "
    + "or provider results. Do not add external storage, project-management applications or writes "
    + "the user did not request. Return native AURA results when allowed. Show the revised plan for approval.";
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

export function unavailablePlanningState(run = {}) {
  return {
    steps: [],
    provisional: true,
    compileState: "blocked",
    compileError: "",
    error: run.error || run.blocker?.message
      || "AURA couldn't verify a safe executable plan. Nothing has run.",
  };
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
