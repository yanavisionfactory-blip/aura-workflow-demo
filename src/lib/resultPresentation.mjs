const PROVIDERS = [
  "Canva",
  "Google Sheets",
  "Google Drive",
  "Gmail",
  "HubSpot",
  "Slack",
  "Jira",
  "Notion",
  "Salesforce",
  "Meta Ads",
];

const TITLE_STOP_WORDS = new Set([
  "a", "an", "and", "for", "from", "in", "of", "on", "the", "to", "with",
]);

const PROVIDER_ALIASES = {
  sheets: "Google Sheets",
  "google sheets": "Google Sheets",
  drive: "Google Drive",
  "google drive": "Google Drive",
  google: "Google Workspace",
  gmail: "Gmail",
  canva: "Canva",
  hubspot: "HubSpot",
  jira: "Jira",
  notion: "Notion",
  slack: "Slack",
  salesforce: "Salesforce",
  "meta-ads": "Meta Ads",
};

const cleanReceiptText = (value = "") => String(value)
  .replace(/^\s*[→✓✔]\s*/, "")
  .replace(/\s+/g, " ")
  .trim();

const safeHttpsUrl = (value) => {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
};

const titleTokens = (value = "") => new Set(
  String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .split(" ")
    .filter((token) => token.length > 2 && !TITLE_STOP_WORDS.has(token))
);

const displayProvider = (value = "") => {
  const normalized = String(value).trim().toLowerCase().replace(/_/g, "-");
  return PROVIDER_ALIASES[normalized]
    || String(value).replace(/(^|[-_])\w/g, (match) => match.replace(/[-_]/, "").toUpperCase());
};

const providerForOutput = (output = {}) => {
  const operation = String(output.operation || "").toLowerCase();
  if (operation.startsWith("gmail.")) return "Gmail";
  if (operation.startsWith("sheets.")) return "Google Sheets";
  if (operation.startsWith("drive.")) return "Google Drive";
  if (operation.startsWith("canva.")) return "Canva";
  return displayProvider(output.tool || operation.split(".")[0]);
};

export function meaningfulMetrics(metrics = []) {
  return metrics.filter((metric) => {
    const label = String(metric?.label || "").trim().toLowerCase();
    return metric?.value != null && label && !/^steps? completed$/.test(label);
  });
}

export function providerForOutcome(outcome = {}) {
  const labelMatch = String(outcome.linkLabel || "").match(/(?:open|view)\s+in\s+(.+)/i);
  if (labelMatch) return displayProvider(labelMatch[1]);
  const text = `${outcome.title || ""} ${outcome.detail || ""}`.toLowerCase();
  return PROVIDERS.find((provider) => text.includes(provider.toLowerCase())) || "";
}

export function selectPrimaryOutcome(results = {}) {
  if (results.primaryResult) return results.primaryResult;
  const outcomes = (results.outcomes || []).filter((outcome) => !outcome.attention);
  if (!outcomes.length) {
    return {
      title: results.title || "Workflow result",
      detail: results.summary || "AURA completed the workflow.",
      provider: "",
    };
  }

  const resultTokens = titleTokens(results.title);
  const scored = outcomes.map((outcome, index) => {
    const overlap = [...titleTokens(outcome.title)].filter((token) => resultTokens.has(token)).length;
    const score = (outcome.primary ? 1000 : 0)
      + (outcome.type === "document" ? 120 : 0)
      + (outcome.items?.length ? 50 : 0)
      + (outcome.link ? 10 : 0)
      + (overlap * 80)
      + (index / 1000);
    return { outcome, score };
  });
  scored.sort((left, right) => right.score - left.score);
  const outcome = scored[0].outcome;
  return { ...outcome, provider: providerForOutcome(outcome) };
}

export function supportingReceipts(results = {}, activity = [], primary = null) {
  const primaryProvider = String(primary?.provider || providerForOutcome(primary || {})).toLowerCase();
  const completed = activity
    .filter((step) => step.status === "completed")
    .filter((step) => !primaryProvider || String(step.tool || "").toLowerCase() !== primaryProvider)
    .map((step) => ({
      key: `${step.tool || "AURA"}:${step.action || step.liveOutput || "completed"}`,
      tool: step.tool || "AURA",
      title: cleanReceiptText(step.liveOutput) || cleanReceiptText(step.action) || "Completed",
    }));

  if (completed.length) {
    return completed.filter((receipt, index, all) =>
      all.findIndex((candidate) => candidate.key === receipt.key) === index
    );
  }

  return (results.outcomes || [])
    .filter((outcome) => !outcome.attention)
    .filter((outcome) => !primary || outcome.title !== primary.title || outcome.link !== primary.link)
    .map((outcome, index) => ({
      key: `${outcome.title || "outcome"}:${index}`,
      tool: providerForOutcome(outcome) || "AURA",
      title: outcome.title || outcome.detail || "Completed",
    }));
}

const canvaDesignId = (result = {}) => {
  const designs = result.job?.result?.designs || result.result?.designs || result.designs || [];
  return designs.find((design) => design?.id)?.id || null;
};

const canvaDownloadUrl = (outputs = []) => {
  for (const output of [...outputs].reverse()) {
    if (!String(output.operation || "").startsWith("canva.export.")) continue;
    const result = output.provider_result || {};
    const candidates = [
      ...(Array.isArray(result.job?.urls) ? result.job.urls : []),
      ...(Array.isArray(result.urls) ? result.urls : []),
      result.url,
      result.download_url,
    ];
    const url = candidates.map(safeHttpsUrl).find(Boolean);
    if (url) return url;
  }
  return null;
};

const outputScore = (output = {}, contextTitle = "") => {
  const operation = String(output.operation || "").toLowerCase();
  const provider = providerForOutput(output);
  const contextTokens = titleTokens(contextTitle);
  const overlap = [...titleTokens(`${provider} ${operation}`)]
    .filter((token) => contextTokens.has(token)).length;
  return (overlap * 100)
    + (/\.(create|update|export)/.test(operation) ? 60 : 0)
    - (/\.(read|search|forecast)/.test(operation) ? 60 : 0)
    - (["gmail.send", "slack.post"].includes(operation) ? 30 : 0);
};

export function primaryResultFromOutputs(outputs = [], context = {}) {
  const completed = outputs.filter((output) => output && typeof output === "object");
  const canva = completed.find((output) => output.operation === "canva.presentation.create");
  if (canva) {
    const result = canva.provider_result || {};
    const designId = canvaDesignId(result);
    const openUrl = safeHttpsUrl(result.result_url)
      || (designId ? `https://www.canva.com/design/${encodeURIComponent(designId)}/edit` : null);
    return {
      title: context.title || "Canva presentation",
      detail: context.deliverable || context.summary || "Your presentation is ready.",
      provider: "Canva",
      kind: "presentation",
      link: openUrl,
      linkLabel: "Open in Canva",
      downloadUrl: canvaDownloadUrl(completed),
    };
  }

  const linked = completed
    .filter((output) => safeHttpsUrl(output.provider_result?.result_url))
    .sort((left, right) => outputScore(right, context.title) - outputScore(left, context.title))[0];
  const link = safeHttpsUrl(linked?.provider_result?.result_url);
  const provider = linked ? providerForOutput(linked) : "";
  return {
    title: context.title || "Workflow result",
    detail: context.deliverable || context.summary || "AURA completed the workflow.",
    provider,
    kind: "result",
    link,
    linkLabel: link ? `Open${provider ? ` in ${provider}` : " result"}` : undefined,
    downloadUrl: null,
  };
}
