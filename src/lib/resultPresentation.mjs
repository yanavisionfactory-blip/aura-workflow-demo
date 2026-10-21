import { jiraReceiptTasks } from "./jiraReceipt.mjs";
import { articleMarkdown, articleWordCount } from "./actionContent.mjs";
import { campaignCopySections } from "./campaignCopySections.mjs";
import { seoAuditManifest } from "./seoAuditResult.mjs";
import { savedCampaignDraft } from "./campaignDrafts.mjs";

export function readableResultText(value, fallback = "Review the saved app results below.") {
  if (typeof value !== "string") return fallback;
  try {
    const parsed = JSON.parse(value);
    const records = Array.isArray(parsed) ? parsed : parsed?.steps || [parsed];
    if (Array.isArray(records) && records.some((item) => item && typeof item === "object"
      && typeof item.operation === "string" && (item.arguments || item.tool_slug || item.depends_on))) return fallback;
  } catch { /* Normal deliverable prose stays readable as written. */ }
  return value;
}

const PROVIDERS = [
  "Canva",
  "Google Sheets",
  "Google Drive",
  "Google Docs",
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
  docs: "Google Docs",
  "google docs": "Google Docs",
  "google drive": "Google Drive",
  "google-docs": "Google Docs",
  "google-drive": "Google Drive",
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
  if (operation.startsWith("docs.")) return "Google Docs";
  if (operation.startsWith("canva.")) return "Canva";
  return displayProvider(output.tool || operation.split(".")[0]);
};

export function meaningfulMetrics(metrics = []) {
  return metrics.filter((metric) => {
    const label = String(metric?.label || "").trim().toLowerCase();
    return metric?.value != null && label && !/^steps? completed$/.test(label);
  });
}

const presentNumber = (value) => {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= 0 ? number : null;
};

const completedOutputs = (activity = []) => activity
  .filter((step) => step.status === "completed" && step.output?.provider_result)
  .map((step) => step.output);

function verifiedDraftArticles(outputs) {
  const verified = outputs.filter((output) => output.outcome_check?.status === "verified" && output.critic?.action === "accept");
  const writes = verified.filter((output) => output.operation === "wordpress-org.update-post");
  const sources = writes.length ? writes : verified.filter((output) => output.operation === "wordpress-org.search-posts"
    && output.resolved_arguments?.statuses?.includes("draft"));
  const posts = new Map();
  for (const output of sources) {
    const returned = output.provider_result?.ret || output.provider_result;
    for (const post of Array.isArray(returned) ? returned : [returned]) {
      if (!post || !Number.isInteger(post.id) || post.status !== "draft"
          || (writes.length && String(post.id) !== String(output.resolved_arguments?.post))) continue;
      const body = typeof post.content === "string" ? post.content : post.content?.raw || post.content?.rendered;
      const title = typeof post.title === "string" ? post.title : post.title?.raw || post.title?.rendered;
      if (typeof body !== "string" || !body.trim() || typeof title !== "string" || !title.trim()) continue;
      posts.set(post.id, { title: articleMarkdown(title), body: articleMarkdown(body), words: articleWordCount(body), reused: !writes.length });
    }
  }
  return [...posts.values()];
}

// Use provider receipts for missing metrics. Never infer time saved or imply
// that the size of a paginated response is the size of the whole audience.
export function resultMetrics(metrics = [], activity = []) {
  const supplied = meaningfulMetrics(metrics);
  if (supplied.length) return supplied.slice(0, 3);
  const outputs = completedOutputs(activity);
  const canva = outputs.find((output) => output.operation === "canva.presentation.create"
    && canvaDesignId(output.provider_result || {}));
  const audiences = outputs.find((output) => output.operation === "mailchimp.audiences.list");
  const email = outputs.find((output) => output.operation === "gmail.send");
  const documents = new Set(outputs.filter((output) => isDocumentCreate(output.operation))
    .map((output) => documentUrl(output.provider_result)).filter(Boolean));
  const reviewedDesigns = new Set(outputs.filter((output) => output.operation === "canva.design.get")
    .map((output) => canvaDesignId(output.provider_result)).filter(Boolean));
  if (reviewedDesigns.size && !canva && !documents.size && !email) {
    const reviewedDocs = new Set(outputs.filter((output) => isDocumentRead(output.operation))
      .map((output) => documentUrl(output.provider_result)).filter(Boolean));
    return [{ value: String(reviewedDesigns.size), label: "existing creatives reviewed" },
      ...(reviewedDocs.size ? [{ value: String(reviewedDocs.size), label: "existing documents checked" }] : [])];
  }
  const savedBodies = outputs.filter((output) => isDocumentCreate(output.operation) && documentUrl(output.provider_result))
    .map((output) => output.resolved_arguments?.body ?? output.resolved_arguments?.content ?? "");
  const campaign = savedBodies.map(campaignCopySections).find(Boolean);
  if (campaign) {
    const reviews = savedBodies.reduce((n, body) => n + (body.match(/^\d+\. .+— Status: (?:Pending|Needs input)\b/gm) || []).length, 0);
    return [{ value: String(campaign.reduce((n, group) => n + group.sections.length, 0)), label: "draft campaign concepts" },
      { value: String(documents.size), label: documents.size === 1 ? "document created" : "documents created" },
      ...(reviews ? [{ value: String(reviews), label: "open review actions" }] : [])];
  }
  const jiraBatch = outputs.find((output) => output.operation === "jira.issues.create_from_blocks");
  const result = [];
  const reviewedArticles = verifiedDraftArticles(outputs);
  if (reviewedArticles.length && reviewedArticles.every((article) => article.reused)) {
    result.push({ value: String(reviewedArticles.length), label: "existing draft articles reviewed" });
  }
  if (jiraBatch) {
    const count = jiraReceiptTasks(jiraBatch.provider_result).length;
    if (count) result.push({ value: String(count), label: count === 1 ? "Jira task created" : "Jira tasks created" });
  }
  if (email) result.push({ value: "1", label: "email sent" });
  if (documents.size) result.push({ value: String(documents.size), label: documents.size === 1 ? "document created" : "documents created" });
  if (canva) {
    const count = presentNumber(canva.provider_result.page_count);
    if (count && count > 0) result.push({ value: String(count), label: count === 1 ? "slide created" : "slides created" });
    else result.push({ value: "1", label: "Canva presentation created" });
  }
  const lists = audiences?.provider_result?.lists;
  if (Array.isArray(lists) && lists.length) {
    result.push({ value: String(lists.length), label: lists.length === 1 ? "audience used" : "audiences read" });
    if (lists.length === 1) {
      const contacts = presentNumber(lists[0]?.stats?.member_count);
      if (contacts !== null) result.push({ value: contacts.toLocaleString("en-US"), label: "contacts in audience" });
    }
  }
  return result.slice(0, 3);
}

const mailchimpAudienceLink = (result = {}) => {
  const audience = Array.isArray(result.lists) ? result.lists[0] : null;
  const webId = presentNumber(audience?.web_id);
  const urls = [Array.isArray(audience?._links) ? audience._links.find((item) => item.rel === "self")?.href : null,
    Array.isArray(result?._links) ? result._links.find((item) => item.rel === "self")?.href : null];
  const dc = urls.map((value) => String(value || "").match(/^https:\/\/(us\d+)\.api\.mailchimp\.com\//i)?.[1]).find(Boolean);
  return dc && webId !== null
    ? `https://${dc}.admin.mailchimp.com/lists/members/?id=${webId}`
    : "https://login.mailchimp.com/";
};

const audiencePreview = (result = {}) => {
  const lists = result.lists;
  if (!Array.isArray(lists) || !lists.length) return [];
  return lists.slice(0, 5).map((audience) => ({
    name: String(audience?.name || "Audience"),
    contacts: presentNumber(audience?.stats?.member_count),
  }));
};

const slideContent = (arguments_ = {}) => {
  if (!Array.isArray(arguments_.phases) || !arguments_.phases.length || !arguments_.title) return null;
  const isRealText = (value) => typeof value === "string" && value.trim() && !/\{\{[^}]+\}\}/.test(value);
  if (!isRealText(arguments_.title) || (arguments_.subtitle && !isRealText(arguments_.subtitle))) return null;
  const slides = arguments_.phases.map((phase) => ({
    period: phase?.period,
    title: phase?.title,
    items: phase?.items,
  }));
  if (slides.some((slide) => !isRealText(slide.period) || !isRealText(slide.title)
    || !Array.isArray(slide.items) || !slide.items.length || slide.items.some((item) => !isRealText(item)))) return null;
  return {
    title: arguments_.title,
    subtitle: arguments_.subtitle || "",
    layout: arguments_.layout === "timeline" ? "timeline" : "slides",
    slides,
  };
};

export function providerForOutcome(outcome = {}) {
  const labelMatch = String(outcome.linkLabel || "").match(/(?:open|view)\s+in\s+(.+)/i);
  if (labelMatch) return displayProvider(labelMatch[1]);
  const text = `${outcome.title || ""} ${outcome.detail || ""}`.toLowerCase();
  return PROVIDERS.find((provider) => text.includes(provider.toLowerCase())) || "";
}

export function selectPrimaryOutcome(results = {}) {
  if (results.primaryResult) {
    // Delivery is a supporting action. Keep the finished presentation visible
    // even when the execution summary records email as its final step.
    if (results.primaryResult.artifact?.kind === "presentation") {
      return { ...results.primaryResult.artifact, delivery: results.primaryResult };
    }
    return results.primaryResult;
  }
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

export function supportingReceipts(results = {}, activity = [], primary = null, presentation = null) {
  const primaryProvider = String(primary?.provider || providerForOutcome(primary || {})).toLowerCase();
  const hasCompiledSelection = Array.isArray(presentation?.supporting_step_keys);
  const supportingKeys = new Set(presentation?.supporting_step_keys || []);
  const completed = activity
    .filter((step) => step.status === "completed")
    .filter((step) => !hasCompiledSelection || supportingKeys.has(step.stepKey || step.key)
      || (primary?.delivery && step.output?.operation === "gmail.send"))
    .filter((step) => !primary?.delivery || step.output?.operation !== "canva.presentation.create")
    .filter((step) => hasCompiledSelection
      || !primaryProvider
      || String(step.tool || "").toLowerCase() !== primaryProvider)
    .map((step) => {
      const providerResult = step.output?.provider_result || {};
      const operation = String(step.output?.operation || "").toLowerCase();
      const designId = operation === "canva.presentation.create"
        ? (providerResult.job?.result?.designs || providerResult.result?.designs || providerResult.designs || [])
          .find((design) => design?.id)?.id
        : null;
      const link = safeHttpsUrl(providerResult.result_url)
        || (designId ? `https://www.canva.com/design/${encodeURIComponent(designId)}/edit` : null)
        || (isDocumentCreate(operation) || isDocumentRead(operation) ? documentUrl(providerResult) : null)
        || (operation === "mailchimp.audiences.list" ? mailchimpAudienceLink(providerResult) : null);
      const tool = operation === "gmail.send" ? "Gmail" : step.tool || "AURA";
      const savedTitle = isDocumentCreate(operation) || isDocumentRead(operation)
        ? providerResult.ret?.title || providerResult.ret?.name || providerResult.title || providerResult.name : null;
      return {
        key: `${step.stepKey || step.key || tool}:${step.action || step.liveOutput || "completed"}`,
        actionId: step.id || step.stepKey || step.key,
        tool,
        title: savedTitle || (/^(?:completed|done|success(?:ful)?)\.?$/i.test(cleanReceiptText(step.liveOutput))
          ? cleanReceiptText(step.action) || "Completed"
          : cleanReceiptText(step.liveOutput) || cleanReceiptText(step.action) || "Completed"),
        link,
        linkLabel: link ? `View in ${tool}` : null,
        preview: operation === "mailchimp.audiences.list" ? audiencePreview(providerResult) : [],
      };
    });

  // A workflow can produce several designs in Canva. Keep the other saved
  // designs and completed downloads reachable even when one is the main result.
  for (const step of activity.filter((item) => item.status === "completed")) {
    const operation = step.output?.operation;
    const result = step.output?.provider_result || {};
    const job = result.job || result;
    if (operation === "canva.design.get" && result.design?.id && result.design.id !== primary?.designId) {
      const link = safeHttpsUrl(result.design.urls?.edit_url);
      if (link) completed.push({ key: `canva-design:${result.design.id}`, tool: "Canva",
        title: result.design.title || "Existing Canva creative", link, linkLabel: "Edit in Canva", preview: [] });
    }
    if (job.status !== "success") continue;
    if (operation === "canva.import.get") {
      for (const design of job.result?.designs || []) {
        if (design.id === primary?.designId) continue;
        const link = safeHttpsUrl(design.urls?.edit_url);
        if (link) completed.push({ key: `canva-design:${design.id}`, tool: "Canva",
          title: design.title || "Saved Canva design", link,
          linkLabel: "Edit in Canva", preview: [] });
      }
    }
    if (operation === "canva.export.get") {
      for (const [index, value] of (job.urls || []).entries()) {
        const link = safeHttpsUrl(value);
        if (link) completed.push({ key: `canva-export:${job.id || step.stepKey}:${index}`,
          tool: "Canva", title: "Completed creative export", link,
          linkLabel: "Download creative", preview: [] });
      }
    }
  }

  if (primary?.delivery && !completed.some((receipt) => receipt.tool.toLowerCase() === "gmail")) {
    completed.push({ key: "presentation-delivery", tool: "Gmail", title: primary.delivery.subject || "Email sent",
      link: safeHttpsUrl(primary.delivery.link), linkLabel: "View in Gmail", preview: [] });
  }

  if (hasCompiledSelection || completed.length) {
    return completed.filter((receipt, index, all) => (!primary?.link || receipt.link !== primary.link)
      && (!primary?.downloadUrl || receipt.link !== primary.downloadUrl)
      && all.findIndex((candidate) => candidate.key === receipt.key || (receipt.link && candidate.link === receipt.link)) === index
    );
  }

  return (results.outcomes || [])
    .filter((outcome) => !outcome.attention)
    .filter((outcome) => !primary || outcome.title !== primary.title || outcome.link !== primary.link)
    .map((outcome, index) => ({
      key: `${outcome.title || "outcome"}:${index}`,
      tool: providerForOutcome(outcome) || "AURA",
      title: outcome.title || outcome.detail || "Completed",
      link: safeHttpsUrl(outcome.link),
      linkLabel: outcome.linkLabel || null,
    }));
}

export function visualResultChoices(activity = [], context = {}) {
  const choices = [];
  for (const step of activity.filter((item) => item.status === "completed")) {
    const output = step.output || {};
    if (!["canva.presentation.create", "canva.design.get"].includes(output.operation)) continue;
    const key = step.stepKey || step.key || output.step_key;
    if (!key) continue;
    const result = primaryResultFromOutputs([{ ...output, step_key: key }], context,
      { primary_step_key: key, artifact_step_key: key });
    if (result.kind !== "presentation" || !result.designId || choices.some((item) => item.result.designId === result.designId)) continue;
    const thumbnail = canvaDesign(output.provider_result || {})?.thumbnail || {};
    const shape = output.resolved_arguments?.canvas || (thumbnail.width && thumbnail.height
      ? thumbnail.width > thumbnail.height ? "landscape" : thumbnail.width === thumbnail.height ? "square" : "portrait" : "creative");
    choices.push({ key, label: `${result.title} — ${shape}`, result });
  }
  return choices;
}

const canvaDesignId = (result = {}) => {
  if (result.design?.id) return result.design.id;
  const designs = result.job?.result?.designs || result.result?.designs || result.designs || [];
  return designs.find((design) => design?.id)?.id || null;
};

const canvaDesign = (result = {}) => {
  if (result.design?.id) return result.design;
  const designs = result.job?.result?.designs || result.result?.designs || result.designs || [];
  return designs.find((design) => design?.id) || null;
};

const canvaThumbnailUrl = (value) => {
  const url = safeHttpsUrl(value);
  if (!url) return null;
  const host = new URL(url).hostname.toLowerCase();
  return host === "canva.com" || host.endsWith(".canva.com") ? url : null;
};

const isDocumentCreate = (operation) => ["docs.create", "google-docs.create-document"].includes(operation);
const isDocumentRead = (operation) => ["docs.get", "google-docs.get-document"].includes(operation);

// Use the saved provider body when available. Reading history never fetches a
// document again, and a read-back of another resource cannot replace this one.
function documentPreview(output, context = {}) {
  if (!output || (!isDocumentRead(output.operation) && !isDocumentCreate(output.operation))) return null;
  const receipt = output.provider_result || {};
  if (receipt.error || receipt.isError || receipt.is_error) return null;
  const doc = receipt.ret || receipt;
  const tabs = Array.isArray(doc.tabs) ? doc.tabs
    .map((tab) => typeof tab?.textContent === "string" ? tab.textContent : "")
    .filter((text) => text.trim()) : [];
  const returnedBody = tabs.length ? tabs.join("\n\n") : doc.textContent ?? doc.body;
  const args = output.resolved_arguments || {};
  const body = typeof returnedBody === "string" && returnedBody.trim() ? returnedBody
    : isDocumentCreate(output.operation) ? args.body ?? args.content : null;
  if (typeof body !== "string" || !body.trim() || /\{\{[^}]+\}\}/.test(body)) return null;
  return { title: doc.title || doc.name || args.title || context.title || "Document", body };
}

const documentId = (result = {}) => [result.ret?.documentId, result.ret?.id, result.documentId, result.id]
  .find((value) => typeof value === "string" && /^[a-zA-Z0-9_-]+$/.test(value));

const documentUrl = (result = {}) => {
  const id = documentId(result);
  return safeHttpsUrl(result.webViewLink) || safeHttpsUrl(result.ret?.webViewLink)
    || safeHttpsUrl(result.ret?.url)
    || (id ? `https://docs.google.com/document/d/${encodeURIComponent(id)}/edit` : null);
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

const canvaArtifactFromOutputs = (outputs = [], context = {}, stepKey = null) => {
  const canva = outputs.find((output) => ["canva.presentation.create", "canva.design.get"].includes(output.operation)
    && (!stepKey || output.step_key === stepKey));
  if (!canva) return null;
  const result = canva.provider_result || {};
  const design = canvaDesign(result);
  const designId = design?.id;
  const reused = canva.operation === "canva.design.get";
  const link = safeHttpsUrl(result.result_url)
    || safeHttpsUrl(design?.urls?.edit_url)
    || (designId ? `https://www.canva.com/design/${encodeURIComponent(designId)}/edit` : null);
  return {
    title: slideContent(canva.resolved_arguments)?.title || design?.title || context.artifactTitle || context.title || "Canva presentation",
    provider: "Canva",
    providerVerb: reused ? "Reused from" : "Created in",
    ...(reused ? { completionTitle: context.title || "Existing campaign creative verified",
      completionSummary: context.summary || "Existing Canva creative checked. Saved content reused." } : {}),
    designId,
    kind: "presentation",
    preview: designId ? slideContent(canva.resolved_arguments) : null,
    thumbnailUrl: designId ? canvaThumbnailUrl(design?.thumbnail?.url) : null,
    link,
    linkLabel: "View presentation",
    downloadUrl: canvaDownloadUrl(outputs),
  };
};

const sentTitle = (value = "") => {
  const title = String(value).trim();
  if (!title) return "Email sent";
  return /\b(sent|emailed|delivered)\b/i.test(title) ? title : `${title} sent`;
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

export function primaryResultFromOutputs(outputs = [], context = {}, presentation = null) {
  const completed = outputs.filter((output) => output && typeof output === "object");
  let explicitPrimary = presentation?.primary_step_key
    ? completed.find((output) => output.step_key === presentation.primary_step_key)
    : null;
  const campaignDraft = savedCampaignDraft(completed, presentation?.primary_step_key || null);
  if (campaignDraft) return { ...campaignDraft, graphic: canvaArtifactFromOutputs(completed, context) };
  const executive = [...completed].reverse().find((output) => output.operation === "executive.review.prepare"
    && output.critic?.action === "accept" && output.outcome_check?.status === "verified"
    && output.provider_result?.kind === "executive_review" && output.provider_result?.synthetic === true
    && output.provider_result?.packet?.execution?.mode === "backend_executed_synthetic"
    && output.provider_result?.packet?.sources?.length === 10);
  if (executive && (!explicitPrimary || explicitPrimary === executive)) return {
    kind: "executive_review", title: "Biweekly executive marketing review", provider: "AURA", providerVerb: "Executed in",
    completionTitle: "Executive review executed in AURA",
    completionSummary: "Ten simulated export processors and executive-review drafting completed. Inspect the review and separate tool receipts in AURA.",
    packet: executive.provider_result.packet, link: null, downloadUrl: null,
  };
  const website = [...completed].reverse().find((output) => output.operation === "website.content.prepare"
    && output.critic?.action === "accept" && output.outcome_check?.status === "verified"
    && output.provider_result?.kind === "website_content"
    && output.provider_result?.status === "draft"
    && output.provider_result?.packet?.execution?.mode === "live_public_sources"
    && output.provider_result?.packet?.pages?.length === 5);
  if (website && (!explicitPrimary || explicitPrimary === website)) return {
    kind: "website_content", title: "Five-page website content package", provider: "AURA",
    completionTitle: "Five-page content package prepared",
    completionSummary: website.provider_result.summary,
    packet: website.provider_result.packet, link: null, downloadUrl: null,
  };
  const weekly = [...completed].reverse().find((output) => output.operation === "weekly.review.prepare"
    && output.critic?.action === "accept" && output.outcome_check?.status === "verified"
    && output.provider_result?.kind === "weekly_review"
    && ((output.provider_result?.synthetic === true && output.provider_result?.packet?.execution?.mode === "backend_executed_synthetic")
      || (output.provider_result?.synthetic === false && output.provider_result?.packet?.provenance === "approved_export"
        && output.provider_result?.packet?.execution?.mode === "backend_executed_approved_exports")
      || (output.provider_result?.synthetic === true && output.provider_result?.packet?.version === 2
        && output.provider_result?.packet?.provenance === "mixed_evidence"
        && output.provider_result?.packet?.execution?.mode === "backend_executed_mixed_evidence")));
  if (weekly && (!explicitPrimary || explicitPrimary === weekly)) return {
    kind: "weekly_review", title: "Weekly account review", provider: "AURA", providerVerb: "Executed in",
    completionTitle: "Weekly review executed in AURA",
    completionSummary: weekly.provider_result.summary || "Source processors and AURA model drafting completed. Inspect separate source results, experiments, draft variants and backlog.",
    packet: weekly.provider_result.packet, link: null, downloadUrl: null,
  };
  const report = [...completed].reverse().find((output) => output.operation === "report.compose"
    && output.critic?.action === "accept" && output.outcome_check?.status === "verified"
    && output.provider_result?.status === "draft"
    && typeof output.provider_result?.body === "string" && output.provider_result.body.trim());
  if (report && (!explicitPrimary || explicitPrimary === report)) {
    const saved = report.provider_result;
    const audit = !saved.synthetic && seoAuditManifest(saved.sources || []);
    if (audit) return {
      title: "SEO audit", kind: "seo_audit", provider: "AURA", providerVerb: "Review in",
      completionTitle: "SEO audit result",
      completionSummary: "Inspect the findings, implementation backlog and actual outcomes from each tool.",
      audit, link: null, downloadUrl: null,
    };
    return {
      title: saved.title || context.title, kind: "report", provider: "AURA", providerVerb: "Saved in",
      completionTitle: "Review draft ready in AURA",
      completionSummary: saved.synthetic
        ? "Fictional client review saved in AURA. All client data is synthetic."
        : saved.summary,
      detail: saved.summary,
      preview: { title: saved.title, body: saved.body, sources: saved.sources || [] },
      link: null, downloadUrl: null,
    };
  }
  // The last verification step confirms completion; the created document is
  // still the deliverable. Only replace a read tied to this run's saved output.
  if (isDocumentRead(explicitPrimary?.operation)) {
    const readId = documentId(explicitPrimary.provider_result)
      || explicitPrimary.resolved_arguments?.document_id || explicitPrimary.resolved_arguments?.documentId;
    const documents = completed.filter((output) => isDocumentCreate(output.operation)
      && documentUrl(output.provider_result)
      && typeof (output.resolved_arguments?.body ?? output.resolved_arguments?.content) === "string");
    if (readId && documents.some((output) => documentId(output.provider_result) === readId)) {
      const wanted = titleTokens(context.title);
      const relevance = (output) => [...titleTokens(output.resolved_arguments.title)].filter((word) => wanted.has(word)).length;
      explicitPrimary = [...documents].sort((a, b) => relevance(b) - relevance(a))[0];
    }
  }
  const articles = verifiedDraftArticles(completed);
  // A read-back of the handoff accompanies the content; it is not the content
  // artifact itself. Keep verified complete drafts visible before that receipt.
  const articleHandoff = explicitPrimary?.operation === "jira.issue.get"
    && articles.every((article) => article.reused);
  if (articles.length && (!explicitPrimary || articleHandoff || explicitPrimary.operation?.startsWith("wordpress-org."))) {
    if (articles.every((article) => article.reused)) return {
      title: "Existing unpublished articles reviewed", kind: "articles", provider: "WordPress", providerVerb: "Reused from",
      completionTitle: "Existing article drafts verified",
      completionSummary: `${articles.length} existing ${articles.length === 1 ? "article reviewed" : "articles reviewed"} in WordPress. Saved content reused; every article remains unpublished.`,
      detail: "Full existing draft bodies were read from WordPress for review.", articles,
    };
    return { title: "Unpublished articles saved", kind: "articles", provider: "WordPress", providerVerb: "Saved in",
      completionTitle: "Unpublished articles saved", completionSummary: `${articles.length} ${articles.length === 1 ? "article saved" : "articles saved"} as drafts in WordPress.`,
      detail: "Complete saved content is available below. Every article remains unpublished.", articles };
  }
  const gmail = explicitPrimary
    ? (explicitPrimary.operation === "gmail.send" ? explicitPrimary : null)
    : [...completed].reverse().find((output) => output.operation === "gmail.send");
  const artifact = canvaArtifactFromOutputs(
    completed,
    context,
    presentation?.artifact_step_key || null
  );
  if (gmail) {
    const receipt = gmail.provider_result || {};
    const recipient = String(receipt.recipient || gmail.resolved_arguments?.to || "").trim();
    const subject = String(receipt.subject || gmail.resolved_arguments?.subject || "").trim();
    const body = String(receipt.body || gmail.resolved_arguments?.body || "").trim();
    const attachments = Array.isArray(receipt.attachments)
      ? receipt.attachments
      : (Array.isArray(gmail.resolved_arguments?.attachments) ? gmail.resolved_arguments.attachments : []);
    const artifactDelivered = Boolean(artifact && Array.isArray(receipt.attachments) && receipt.attachments.length > 0);
    const link = safeHttpsUrl(receipt.result_url);
    return {
      title: sentTitle(context.title),
      completionTitle: sentTitle(context.title),
      completionSummary: recipient
        ? `Delivered through Gmail to ${recipient}${artifactDelivered ? " with the finished presentation attached." : "."}`
        : `Delivered through Gmail${artifactDelivered ? " with the finished presentation attached." : "."}`,
      detail: context.deliverable || context.summary || "The requested email was sent successfully.",
      provider: "Gmail",
      providerVerb: "Sent with",
      kind: "email",
      link,
      linkLabel: "Open in Gmail",
      recipient,
      subject,
      body,
      attachments,
      artifact,
      artifactDelivered,
      downloadUrl: artifact?.downloadUrl || null,
    };
  }

  const jiraPrimary = explicitPrimary?.operation === "jira.issues.create_from_blocks"
    ? explicitPrimary
    : !explicitPrimary ? [...completed].reverse().find((output) => output.operation === "jira.issues.create_from_blocks") : null;
  if (jiraPrimary) {
    const tasks = jiraReceiptTasks(jiraPrimary.provider_result || {});
    return {
      title: "Jira tasks created",
      completionTitle: "Jira tasks created",
      completionSummary: `${tasks.length} ${tasks.length === 1 ? "task" : "tasks"} created from your Notion notes.`,
      detail: "Your tasks are ready in Jira.",
      provider: "Jira",
      providerVerb: "Created in",
      kind: "jira_tasks",
      tasks,
      link: tasks[0]?.url || null,
      linkLabel: "Open in Jira",
    };
  }
  if (artifact && (!explicitPrimary || ["canva.presentation.create", "canva.design.get"].includes(explicitPrimary.operation))) {
    return {
      ...artifact,
      detail: context.deliverable || context.summary || "Your presentation is ready.",
      linkLabel: "Open in Canva",
    };
  }

  const linked = explicitPrimary || completed
    .filter((output) => safeHttpsUrl(output.provider_result?.result_url)
      || ((isDocumentCreate(output.operation) || isDocumentRead(output.operation)) && documentUrl(output.provider_result)))
    .sort((left, right) => outputScore(right, context.title) - outputScore(left, context.title))[0];
  const link = safeHttpsUrl(linked?.provider_result?.result_url)
    || ((isDocumentCreate(linked?.operation) || isDocumentRead(linked?.operation)) ? documentUrl(linked.provider_result) : null);
  const provider = linked ? providerForOutput(linked) : "";
  const linkedDocId = (isDocumentCreate(linked?.operation) || isDocumentRead(linked?.operation))
    ? documentId(linked.provider_result) : null;
  const readback = linkedDocId && [...completed].reverse().find((output) => isDocumentRead(output.operation)
    && documentId(output.provider_result) === linkedDocId && documentPreview(output, context));
  const docPreview = documentPreview(readback || linked, context);
  const operation = String(linked?.operation || "");
  const providerVerb = /[.-]update(?:[.-]|$)/.test(operation) ? "Updated in"
    : /[.-](?:get|read|search|list)(?:[.-]|$)/.test(operation) ? "Checked in"
    : /[.-]create(?:[.-]|$)/.test(operation) ? "Created in" : "Result from";
  return {
    title: docPreview?.title || context.title || "Workflow result",
    detail: readableResultText(context.deliverable || context.summary || "AURA completed the workflow."),
    provider,
    providerVerb,
    kind: docPreview ? "document" : "result",
    preview: docPreview,
    link,
    linkLabel: link ? `Open${provider ? ` in ${provider}` : " result"}` : undefined,
    downloadUrl: null,
  };
}
