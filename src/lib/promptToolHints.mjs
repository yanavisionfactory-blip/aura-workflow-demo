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

function catalogPhrases(tool, ambiguousProviders = new Set()) {
  const providerKeys = new Set([
    normalize(tool?.provider),
    normalize(tool?.canonicalProvider),
  ].filter(Boolean));
  return [
    tool?.name,
    tool?.provider,
    tool?.canonicalProvider,
    ...(Array.isArray(tool?.aliases) ? tool.aliases : []),
  ].filter((phrase) => {
    if (!phrase) return false;
    const key = normalize(phrase);
    return !providerKeys.has(key) || !ambiguousProviders.has(key);
  });
}

/**
 * Return immediate, deterministic tool hints while the user is still typing.
 * Explicit catalog names win, then stable language-level intent mappings fill
 * in obvious capabilities. This path never calls the planner or a provider.
 */
export function promptToolHints(value = "", catalog = [], limit = 6) {
  const text = normalize(value);
  if (!text) return [];

  const providerCounts = new Map();
  catalog.forEach((tool) => {
    const keys = new Set([
      normalize(tool?.provider),
      normalize(tool?.canonicalProvider),
    ].filter(Boolean));
    keys.forEach((key) => providerCounts.set(key, (providerCounts.get(key) || 0) + 1));
  });
  const ambiguousProviders = new Set(
    [...providerCounts].filter(([, count]) => count > 1).map(([key]) => key),
  );

  const candidates = [];
  const add = (label, position, priority) => {
    if (!label || candidates.some((item) => item.label === label)) return;
    candidates.push({ label, position, priority });
  };

  catalog.forEach((tool) => {
    const positions = catalogPhrases(tool, ambiguousProviders)
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

/**
 * Keep language-derived suggestions separate from the resources the user has
 * explicitly selected. Suggestions start unselected, may be selected without
 * disappearing, and may be dismissed for the current prompt.
 */
export function promptToolChoices(suggested = [], selected = [], dismissed = []) {
  const selectedSet = new Set(selected.filter(Boolean));
  const dismissedSet = new Set(dismissed.filter(Boolean));
  const seen = new Set();
  const choices = [];

  suggested.filter(Boolean).forEach((label) => {
    if (seen.has(label) || dismissedSet.has(label)) return;
    seen.add(label);
    choices.push({ label, suggested: true, selected: selectedSet.has(label) });
  });

  selected.filter(Boolean).forEach((label) => {
    if (seen.has(label)) return;
    seen.add(label);
    choices.push({ label, suggested: false, selected: true });
  });

  return choices;
}
