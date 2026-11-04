import { CATALOG, catalogEntryFor } from "./toolCatalog.js";
import { planConnectionKey, planConnectionRoute } from "./connectionSelection.mjs";

const resolveTool = (raw) => {
  if (!raw || typeof raw !== "string") return null;
  const key = raw.trim().toLowerCase();
  if (key === "aura intelligence") return null;
  return catalogEntryFor(key)?.name || null;
};

const slugifyTool = (value) => String(value || "")
  .trim()
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, "-")
  .replace(/^-|-$/g, "");

const REQUIREMENT_ALIASES = {
  google: "Google Drive",
  "google-workspace": "Google Drive",
  atlassian: "Jira",
  jira: "Jira",
};

export const resolveRequirementTool = (raw, permissions = []) => {
  const value = String(raw || "").trim();
  if (["google", "google-workspace"].includes(slugifyTool(value))) {
    if (permissions.some((operation) => operation.startsWith("gmail."))) return "Gmail";
    if (permissions.some((operation) => operation.startsWith("calendar."))) return "Google Calendar";
    if (permissions.some((operation) => operation.startsWith("docs."))) return "Google Docs";
    if (permissions.some((operation) => operation.startsWith("sheets."))) return "Google Sheets";
  }
  const catalogMatch = catalogEntryFor(value);
  if (catalogMatch) return catalogMatch.name;
  const slug = slugifyTool(value);
  if (REQUIREMENT_ALIASES[slug]) return REQUIREMENT_ALIASES[slug];
  const exact = CATALOG.find(
    (tool) => slugifyTool(tool.name) === slug || tool.name.toLowerCase() === value.toLowerCase()
  );
  if (exact) return exact.name;
  const contained = CATALOG.find((tool) => value.toLowerCase().includes(tool.name.toLowerCase()));
  return contained?.name || value;
};

const toolsForStep = (step) => {
  const names = [step.tool, ...(step.flow || []).filter((item) => item.label === "Uses").map((item) => item.value)]
    .map(resolveTool)
    .filter(Boolean);
  return [...new Set(names)];
};

// Recompute the checklist from this proposal so a revision cannot retain
// account requirements that belonged to the previous plan.
export function buildPlanConnectionTools(steps = [], plan = {}) {
  const seen = new Set();
  const out = [];
  steps.forEach((s) => {
    toolsForStep(s).forEach((t) => {
      const provider = resolveTool(s.tool) === t ? s.toolSlug || s.tool_slug || null : null;
      const key = planConnectionKey(t, provider);
      if (!t || seen.has(key)) return;
      seen.add(key);
      const match = steps.find(
        (st) =>
          resolveTool(st.tool) === t ||
          (st.flow || []).some((f) => f.label === "Uses" && resolveTool(f.value) === t)
      );
      out.push({ key, name: t, provider, reason: match ? match.iWill || match.action || "" : "" });
    });
  });
  const requirements = plan.connectionChecklist?.length
    ? plan.connectionChecklist.filter((requirement) => requirement.status !== "satisfied")
    : (plan.connectionRequirements || []);
  requirements.forEach((requirement) => {
    const raw = planConnectionRoute(requirement);
    const name = resolveRequirementTool(raw, requirement.required_permissions);
    if (!name) return;
    const provider = raw;
    const key = planConnectionKey(name, provider);
    const accessNeeded = typeof requirement === "object"
      && String(requirement.reason || "").startsWith("Authorize exact operations");
    const existing = out.find((item) => item.name === name
      && (!item.provider || item.provider === provider));
    if (existing) {
      seen.delete(existing.key);
      existing.key = key;
      existing.provider = provider;
      seen.add(key);
      if (existing && accessNeeded) existing.accessNeeded = true;
      return;
    }
    if (seen.has(key)) return;
    seen.add(key);
    out.push({
      key,
      name,
      provider,
      accessNeeded,
      reason: typeof requirement === "object" && requirement.reason
        ? requirement.reason
        : `AURA needs ${name} access to finish building this plan`,
    });
  });
  return out;
}

