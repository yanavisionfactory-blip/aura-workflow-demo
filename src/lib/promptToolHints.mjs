const normalize = (value) => String(value || "")
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, " ")
  .trim();

const containsPhrase = (text, phrase) => {
  const normalized = normalize(phrase);
  return Boolean(normalized) && ` ${text} `.includes(` ${normalized} `);
};

const SEMANTIC_HINTS = [
  { label: "AURA Weather", keywords: ["weather", "forecast", "temperature", "rain", "precipitation"] },
  { label: "Canva", keywords: ["presentation", "presentations", "deck", "decks", "slide", "slides", "design"] },
  { label: "Gmail", keywords: ["email", "emails", "gmail", "inbox", "follow up", "follow-up"] },
  { label: "Slack", keywords: ["slack", "channel", "notify the team", "message the team"] },
  { label: "Google Calendar", keywords: ["calendar", "schedule a meeting", "book a meeting", "invite"] },
  { label: "Google Sheets", keywords: ["sheet", "sheets", "spreadsheet", "spreadsheets", "csv"] },
  { label: "Notion", keywords: ["notion", "wiki"] },
  { label: "Jira", keywords: ["jira", "ticket", "tickets"] },
  { label: "HubSpot", keywords: ["hubspot", "crm", "pipeline"] },
  { label: "Salesforce", keywords: ["salesforce"] },
  { label: "Meta Ads", keywords: ["meta ads", "facebook ads", "meta advertising"] },
];

function catalogPhrases(tool) {
  return [
    tool?.name,
    tool?.provider,
    tool?.canonicalProvider,
    ...(Array.isArray(tool?.aliases) ? tool.aliases : []),
  ].filter(Boolean);
}

/**
 * Return immediate, deterministic tool hints while the user is still typing.
 * Explicit catalog names win, then stable language-level intent mappings fill
 * in obvious capabilities. This path never calls the planner or a provider.
 */
export function promptToolHints(value = "", catalog = [], limit = 6) {
  const text = normalize(value);
  if (!text) return [];

  const candidates = [];
  const add = (label, position, priority) => {
    if (!label || candidates.some((item) => item.label === label)) return;
    candidates.push({ label, position, priority });
  };

  catalog.forEach((tool) => {
    const positions = catalogPhrases(tool)
      .map(normalize)
      .filter((phrase) => containsPhrase(text, phrase))
      .map((phrase) => text.indexOf(phrase));
    if (positions.length) add(tool.name, Math.min(...positions), 0);
  });

  SEMANTIC_HINTS.forEach((hint) => {
    const positions = hint.keywords
      .map(normalize)
      .filter((keyword) => containsPhrase(text, keyword))
      .map((keyword) => text.indexOf(keyword));
    if (!positions.length) return;
    if (hint.label !== "AURA Weather") {
      const available = catalog.some((tool) => tool?.name === hint.label);
      if (!available) return;
    }
    add(hint.label, Math.min(...positions), 1);
  });

  return candidates
    .sort((left, right) => left.position - right.position || left.priority - right.priority)
    .slice(0, limit)
    .map((item) => item.label);
}
