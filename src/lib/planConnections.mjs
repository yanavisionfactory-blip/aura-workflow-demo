import { catalogEntryFor } from "./toolCatalog.js";
import { planConnectionKey, planConnectionRoute } from "./connectionSelection.mjs";

const GOOGLE_APPS = {
  gmail: "Gmail",
  calendar: "Google Calendar",
  docs: "Google Docs",
  sheets: "Google Sheets",
  drive: "Google Drive",
};
const slugify = (value) => String(value || "").trim().toLowerCase()
  .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const resolveTool = (raw) => raw && raw !== "AURA Intelligence"
  ? catalogEntryFor(raw, { allowAliases: false, includeUnavailable: true })?.name || null : null;
const googleApp = (operation) => GOOGLE_APPS[String(operation || "").split(".")[0]];

export function planConnectionRequirements(plan = {}) {
  return plan.connectionChecklist?.length
    ? plan.connectionChecklist.filter((item) => item.status !== "satisfied")
    : (plan.connectionRequirements || []);
}

// A shared Google account is an execution route, not a request for Drive.
// Label each required permission by its actual app, including mixed grants.
export function requirementTools(requirement, steps = []) {
  const provider = planConnectionRoute(requirement);
  const permissions = requirement?.required_permissions || [];
  let names;
  if (["google", "google-workspace"].includes(slugify(provider))) {
    const operations = permissions.length ? permissions : steps
      .filter((step) => (step.toolSlug || step.tool_slug) === provider)
      .map((step) => step.operation);
    names = [...new Set(operations.map(googleApp).filter(Boolean))];
    if (!names.length) names = ["Google Workspace"];
  } else {
    const name = resolveTool(provider)
      || GOOGLE_APPS[slugify(provider).replace(/^google-/, "")]
      || ({ atlassian: "Jira", jira: "Jira" })[slugify(provider)]
      || provider;
    names = name ? [name] : [];
  }
  return names.map((name) => ({
    key: planConnectionKey(name, provider), name, provider,
    accessNeeded: String(requirement?.reason || "").startsWith("Authorize exact operations"),
    requiredPermissions: permissions.filter((operation) => !googleApp(operation) || googleApp(operation) === name),
    reason: `AURA needs ${name} access for the actions in this plan`,
  }));
}

export function buildPlanConnectionTools(steps = [], plan = {}) {
  const tools = [];
  for (const step of steps) {
    const provider = step.toolSlug || step.tool_slug;
    // An executable route is authoritative. Display copy and marketplace
    // search aliases cannot add another app or turn built-in report.compose
    // (displayed as ChatGPT) into an external account requirement.
    if (provider) {
      if (provider === "aura") continue;
      for (const tool of requirementTools({ provider_hint: provider,
        required_permissions: step.operation ? [step.operation] : [] }, steps)) {
        // Custom account routes can be absent from the public app catalog.
        // Only an authoritative missing requirement should gate those routes.
        if (tool.name === provider && !resolveTool(provider)) continue;
        const existing = tools.find((item) => item.key === tool.key);
        if (existing) existing.requiredPermissions = [...new Set([
          ...existing.requiredPermissions, ...tool.requiredPermissions,
        ])];
        else tools.push({ ...tool, reason: step.iWill || step.action || "" });
      }
      continue;
    }
    const names = [step.tool, ...(step.flow || [])
      .filter((item) => item.label === "Uses").map((item) => item.value)]
      .map(resolveTool).filter(Boolean);
    for (const name of new Set(names)) {
      const key = planConnectionKey(name, null);
      if (!tools.some((tool) => tool.key === key)) tools.push({
        key, name, provider: null, reason: step.iWill || step.action || "", requiredPermissions: [],
      });
    }
  }
  for (const requirement of planConnectionRequirements(plan)) {
    for (const tool of requirementTools(requirement, steps)) {
      const existing = tools.find((item) => item.name === tool.name
        && (!item.provider || item.provider === tool.provider));
      if (existing) {
        existing.key = tool.key;
        existing.provider = tool.provider;
        existing.accessNeeded ||= tool.accessNeeded;
        existing.requiredPermissions = [...new Set([...existing.requiredPermissions, ...tool.requiredPermissions])];
      } else tools.push(tool);
    }
  }
  return tools;
}

export function hasPlanConnectionGrant(tool, account) {
  return Boolean(account) && (!tool.provider || account.slug === tool.provider)
    && (tool.requiredPermissions || []).every((operation) => (account.allowed_operations || []).includes(operation));
}
