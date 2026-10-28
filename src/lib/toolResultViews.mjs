import { primaryResultFromOutputs } from "./resultPresentation.mjs";
import { toolEvidence } from "./toolEvidence.mjs";
import { operationProviderName } from "./providerDisplay.mjs";

const names = {
  anthropic: "Claude", claude: "Claude",
  aura: "AURA Intelligence", "aura intelligence": "AURA Intelligence",
  google: "Google Workspace", "google-ads": "Google Ads", "meta-ads": "Meta Ads",
  googleads: "Google Ads", metaads: "Meta Ads",
  "meta-ads-simulated": "Meta Ads · Simulated", "klaviyo-simulated": "Klaviyo · Simulated",
  "google-docs": "Google Docs", docs: "Google Docs", "google-sheets": "Google Sheets",
  sheets: "Google Sheets", "google-drive": "Google Drive", drive: "Google Drive",
  gmail: "Gmail", mailchimp: "Mailchimp", klaviyo: "Klaviyo", canva: "Canva",
  jira: "Jira", slack: "Slack", notion: "Notion", hubspot: "HubSpot", salesforce: "Salesforce",
  frameio: "Frame.io", frame: "Frame.io", "frame.io": "Frame.io", "frame-io": "Frame.io",
};

export function toolResultName(name = "AURA", operation = "") {
  if (operation.startsWith("frameio.")) return "Frame.io";
  if (["report.compose", "web.page.read", "web.search", "intelligence.claude_backup"].includes(operation)) return operationProviderName(name, operation);
  for (const [prefix, label] of [["docs.", "Google Docs"], ["sheets.", "Google Sheets"],
    ["drive.", "Google Drive"], ["gmail.", "Gmail"]]) {
    if (operation.startsWith(prefix)) return label;
  }
  return names[String(name).toLowerCase().replaceAll("_", "-")] || name || "AURA Intelligence";
}

export const toolResultStatus = (entry) => ({ completed: "Completed", failed: "Failed",
  provider_error: "Provider error", blocked: "Needs attention", pending: "Not run",
  running: "Running", recovering: "Checking response", skipped: "Skipped",
  awaiting_approval: "Awaiting review" })[entry.status] || entry.status;

// Only persisted steps become tool actions. Report prose and source packets do
// not become invented provider calls, including when a report names other apps.
export function toolResultEntries(activity = []) {
  return toolEvidence(activity).map((entry, index) => {
    const step = activity[index];
    const output = { ...step.output, step_key: step.stepKey || step.key || step.output?.step_key,
      step_id: step.id, provider_result: entry.response, resolved_arguments: entry.inputs };
    const candidate = entry.status === "completed" && entry.hasResponse
      ? primaryResultFromOutputs([output], { title: entry.action }) : null;
    return { ...entry, tool: toolResultName(entry.tool, entry.operation),
      stepKey: step.stepKey || step.key || output.step_key,
      preview: candidate?.kind && candidate.kind !== "result" ? candidate : null,
      link: candidate?.link || null,
      source: entry.operation === "weekly.source.analyze" ? entry.response?.source : null,
      synthetic: entry.response?.synthetic === true || entry.response?.receipt?.synthetic === true,
    };
  });
}

export function mainToolEntry(entries, primary = {}, presentation = {}) {
  presentation ||= {};
  if (primary.sourceStepKey || primary.sourceStepId) {
    const exact = entries.find((entry) => (primary.sourceStepKey && entry.stepKey === primary.sourceStepKey)
      || (primary.sourceStepId && entry.id === primary.sourceStepId));
    if (exact) return exact;
  }
  const matching = entries.find((entry) => {
    if (primary.link && primary.link === entry.link) return true;
    const preview = entry.preview;
    if (!preview) return false;
    if (primary.designId) return primary.designId === preview.designId;
    if (primary.preview?.body) return primary.preview.body === preview.preview?.body;
    return primary.link && primary.link === preview.link;
  });
  if (matching) return matching;
  const key = primary.kind === "presentation" ? presentation.artifact_step_key || presentation.primary_step_key
    : presentation.primary_step_key;
  return key ? entries.find((entry) => entry.stepKey === key) : undefined;
}

export function toolResultGroups(entries) {
  return [...new Set(entries.map((entry) => entry.tool))].map((tool) => ({
    tool, entries: entries.filter((entry) => entry.tool === tool),
  }));
}
