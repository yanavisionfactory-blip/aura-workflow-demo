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

const PROMPT_TOOL_ALIASES = {
  "meta-ads": ["meta ads", "facebook ads", "meta advertising"],
};

const normalizedWords = (value) => String(value || "")
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, " ")
  .trim();

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
