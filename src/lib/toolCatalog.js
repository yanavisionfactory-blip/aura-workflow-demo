// The selectable catalog is owned by the backend. Only built-in providers or
// signed Connector Engineer releases receive a Connect button. Discovered
// providers remain searchable in MARKETPLACE while AURA verifies them.

const ICONS = {
  google: "✨",
  gmail: "📧",
  "google-drive": "🗂️",
  "google-calendar": "📅",
  "google-sheets": "📊",
  airtable: "🗃️",
  notion: "📝",
  slack: "💬",
  tiktok: "🎵",
  mailchimp: "✉️",
  canva: "🎨",
  hubspot: "🔶",
  jira: "✅",
};

const NATIVE_FALLBACK = [
  { name: "Gmail", provider: "google", icon: ICONS.gmail, desc: "Read and send email" },
  { name: "Google Drive", provider: "google", icon: ICONS["google-drive"], desc: "Access files and folders" },
  { name: "Google Calendar", provider: "google", icon: ICONS["google-calendar"], desc: "Read and create events" },
  { name: "Google Sheets", provider: "google", icon: ICONS["google-sheets"], desc: "Read and write spreadsheets" },
  { name: "Airtable", provider: "airtable", icon: ICONS.airtable, desc: "Read and write records" },
  { name: "Notion", provider: "notion", icon: ICONS.notion, desc: "Read and edit notes and docs" },
  { name: "Slack", provider: "slack", icon: ICONS.slack, desc: "Send messages to channels" },
  { name: "TikTok", provider: "tiktok", icon: ICONS.tiktok, desc: "Read profiles and publish content" },
  { name: "Mailchimp", provider: "mailchimp", icon: ICONS.mailchimp, desc: "Manage audiences and campaigns" },
  { name: "Canva", provider: "canva", icon: ICONS.canva, desc: "Create and export designs" },
  { name: "HubSpot", provider: "hubspot", icon: ICONS.hubspot, desc: "Manage contacts and deals" },
  { name: "Jira", provider: "jira", icon: ICONS.jira, desc: "Create and track issues" },
].map((tool) => ({
  ...tool,
  connectable: true,
  availability: "available",
  connectionStrategy: "oauth",
  setupHint: "Provider consent",
  connectionBackend: "native",
}));

export const CATALOG = [...NATIVE_FALLBACK];
export const MARKETPLACE = [...NATIVE_FALLBACK];

function description(item) {
  const categories = Array.isArray(item.categories) ? item.categories.filter(Boolean) : [];
  const setupHint = String(item.setup_hint || item.setupHint || "").trim();
  if (item.connectable && setupHint && item.capability_count) {
    return `${setupHint} · ${item.capability_count} verified ${item.capability_count === 1 ? "capability" : "capabilities"}`;
  }
  if (item.connectable && setupHint) return setupHint;
  if (categories.length) return categories.slice(0, 2).join(" · ");
  return item.connectable ? "Secure connection available" : "Coming soon";
}

function normalize(item) {
  const provider = String(item.provider || "").trim().toLowerCase();
  if (!provider) return null;
  return {
    name: String(item.display_name || provider),
    provider,
    icon: ICONS[provider] || "🔗",
    logoUrl: String(item.logo_url || "").startsWith("https://") ? item.logo_url : null,
    desc: description(item),
    categories: Array.isArray(item.categories) ? item.categories : [],
    connectable: Boolean(item.connectable ?? item.availability === "available"),
    requestable: Boolean(item.requestable || item.availability === "requestable"),
    availability: item.availability || (item.connectable ? "available" : "verifying"),
    source: item.source || "connector_engineer",
    connectionBackend: item.connection_backend || item.connectionBackend || null,
    connectionStrategy: item.connection_strategy || item.connectionStrategy || null,
    executionBackend: item.execution_backend || item.executionBackend || null,
    setupHint: item.setup_hint || item.setupHint || null,
  };
}

export function searchMarketplace(query, limit = 120) {
  const displayName = String(query || "").trim().replace(/\s+/g, " ");
  const needle = displayName.toLowerCase();
  const matches = MARKETPLACE.filter((tool) => {
    if (!needle) return true;
    return tool.name.toLowerCase().includes(needle) ||
      tool.provider.includes(needle) ||
      tool.categories?.some((category) => category.toLowerCase().includes(needle));
  });
  if (matches.length || displayName.length < 2) return matches.slice(0, limit);

  const requestedSlug = needle.replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "app";
  return [{
    name: displayName,
    provider: `requested:${requestedSlug}`,
    icon: "＋",
    logoUrl: null,
    desc: "Not in the current directory — ask AURA to add it",
    categories: ["Requested apps"],
    connectable: false,
    requestable: true,
    availability: "requestable",
    source: "search_request",
  }];
}

function expandGoogle(item) {
  if (item.provider !== "google" || !item.connectable) return [item];
  return NATIVE_FALLBACK.filter((tool) => tool.provider === "google");
}

function replace(target, items) {
  target.splice(0, target.length, ...items);
}

export function mergeMarketplaceApps(items = []) {
  const byProvider = new Map(MARKETPLACE.map((item) => [item.provider, item]));
  items.forEach((raw) => {
    const item = normalize(raw);
    if (!item) return;
    const current = byProvider.get(item.provider);
    if (!current || item.connectable || !current.connectable) byProvider.set(item.provider, item);
  });
  const marketplace = [...byProvider.values()].sort(
    (a, b) => Number(b.connectable) - Number(a.connectable) || a.name.localeCompare(b.name),
  );
  replace(MARKETPLACE, marketplace);
  replace(CATALOG, marketplace.filter((item) => item.connectable));
}

export function replaceToolCatalog(status = {}) {
  const hasMarketplace = Array.isArray(status.marketplace) && status.marketplace.length;
  const rawMarketplace = hasMarketplace ? status.marketplace : status.catalog;
  if (!Array.isArray(rawMarketplace) || !rawMarketplace.length) return;

  const marketplace = [];
  const seen = new Set();
  rawMarketplace.forEach((raw) => {
    const normalized = normalize(hasMarketplace ? raw : { ...raw, connectable: true });
    if (!normalized) return;
    expandGoogle(normalized).forEach((item) => {
      const key = `${item.provider}:${item.name.toLowerCase()}`;
      if (seen.has(key)) return;
      seen.add(key);
      marketplace.push(item);
    });
  });
  marketplace.sort((a, b) => Number(b.connectable) - Number(a.connectable) || a.name.localeCompare(b.name));
  replace(MARKETPLACE, marketplace);
  replace(CATALOG, marketplace.filter((item) => item.connectable));
}

export function catalogEntryFor(toolName) {
  const key = String(toolName || "").trim().toLowerCase();
  return CATALOG.find((item) => item.name.toLowerCase() === key || item.provider === key) || null;
}

export function providerForTool(toolName) {
  return catalogEntryFor(toolName)?.provider || null;
}
