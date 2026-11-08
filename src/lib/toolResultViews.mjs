import { primaryResultFromOutputs } from "./resultPresentation.mjs";
import { toolEvidence } from "./toolEvidence.mjs";
import { intelligenceBackupNotice, operationProviderName } from "./providerDisplay.mjs";
import { googleSheetsResult, spreadsheetId } from "./googleSheetsResult.mjs";

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
  operation ||= "";
  if (["meta-ads-direct", "meta-ads-mcp"].includes(name) || /^agent-meta-ads-[a-f0-9]+$/.test(name)) return "Meta Ads";
  if (operation.startsWith("frameio.")) return "Frame.io";
  if (operation.startsWith("meta-ads.")) return "Meta Ads";
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

function savedSourceLink(entry) {
  if (entry.operation !== "web.page.read" || entry.status !== "completed") return null;
  try {
    const url = new URL(entry.response?.url);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

// Only persisted steps become tool actions. Report prose and source packets do
// not become invented provider calls, including when a report names other apps.
export function toolResultEntries(activity = []) {
  return toolEvidence(activity).map((entry, index) => {
    const step = activity[index];
    const output = { ...step.output, step_key: step.stepKey || step.key || step.output?.step_key,
      step_id: step.id, operation: entry.operation, provider_result: entry.response, resolved_arguments: entry.inputs };
    const candidate = entry.status === "completed" && entry.hasResponse
      ? primaryResultFromOutputs([output], { title: entry.action }) : null;
    const backupNotice = intelligenceBackupNotice(step);
    const fallback = step.output?.fallback;
    const actualTool = toolResultName(entry.tool, entry.operation);
    const tool = backupNotice && fallback?.status === "used" && fallback.requested_tool && fallback.requested_operation
      ? toolResultName(fallback.requested_tool, fallback.requested_operation) : actualTool;
    const metaAction = tool === "Meta Ads" && /agent-meta-ads-[a-f0-9]+/.test(entry.action || "")
      ? { get_ad_accounts: "Discover Meta ad accounts", get_account_info: "Read Meta account details",
        get_campaigns: "Read Meta campaigns", get_insights: "Read Meta performance" }[entry.operation] : null;
    return { ...entry, action: metaAction || entry.action, tool, actualTool, backupNotice, runId: step.runId, originalStepKey: step.originalStepKey,
      stepKey: step.stepKey || step.key || output.step_key,
      preview: candidate?.kind && candidate.kind !== "result" ? { ...candidate, displayProvider: tool } : null,
      link: candidate?.link || savedSourceLink(entry),
      linkLabel: candidate?.linkLabel || (entry.operation === "web.page.read" ? "Open source" : `Open in ${tool}`),
      source: entry.operation === "weekly.source.analyze" ? entry.response?.source : null,
      synthetic: entry.response?.synthetic === true || entry.response?.receipt?.synthetic === true,
    };
  });
}

// The deliverable leads the final page; every other completed tool stays visible.
// Execution uses the original order instead of this final-results ordering.
export function supportingToolOutputs(entries, primary = {}, presentation = {}) {
  const main = mainToolEntry(entries, primary, presentation);
  const primaryTool = main?.tool || toolResultName(primary.provider);
  return toolResultGroups(entries.filter((entry) => entry.status === "completed" && entry.hasResponse))
    .filter((group) => group.tool !== primaryTool);
}

export function preferredToolOutcome(primary, activity = []) {
  if (!["spreadsheet", "ai_response", "report", "result"].includes(primary.kind)) return primary;
  const outputs = activity.filter((step) => step.status === "completed").map((step) => ({
    ...step.output, step_id: step.id, step_key: step.stepKey || step.key,
    operation: step.output?.operation || step.operation,
  }));
  const canva = primaryResultFromOutputs(outputs.filter((output) => output.operation?.startsWith("canva.") && output.critic?.action === "accept" && output.outcome_check?.status === "verified"), { title: primary.title });
  if (canva?.kind === "presentation" && canva.designId) return canva;
  if (primary.kind === "spreadsheet") {
    const saved = googleSheetsResult(outputs.filter((output) => spreadsheetId(output) === primary.spreadsheetId), { title: primary.title });
    return saved && (saved.ranges.length || !primary.ranges?.length) ? { ...primary, ...saved } : primary;
  }
  // A saved spreadsheet is the deliverable; a source-only read stays secondary.
  const sheet = googleSheetsResult(outputs, { title: primary.title });
  if (sheet) return sheet;
  return primary;
}

export function toolOutputResult(entries, activity = []) {
  const outputs = entries.map((entry) => {
    const step = activity.find((item) => (item.id || item.stepKey || item.key) === entry.id);
    return step?.output ? { ...step.output, step_id: entry.id, step_key: entry.stepKey, operation: entry.operation,
      provider_result: entry.response, resolved_arguments: entry.inputs } : null;
  }).filter(Boolean);
  const candidate = primaryResultFromOutputs(outputs, { title: entries.at(-1)?.action });
  return candidate.kind && candidate.kind !== "result" ? candidate : null;
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
