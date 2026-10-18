export function deliveryLink(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    let sensitive = false;
    url.searchParams.forEach((_value, key) => { if (/token|secret|password|api.?key|access.?code/i.test(key)) sensitive = true; });
    if (sensitive) return null;
    return url.href;
  } catch { return null; }
}

export function deliverySourceLinks(values = {}) {
  const links = {};
  for (const key of ["intake", "research", "report"]) {
    if (!values[key]?.trim()) continue;
    const safe = deliveryLink(values[key].trim());
    if (!safe || new URL(safe).hostname !== "docs.google.com" || !/^\/document\/d\/[^/]+(?:\/edit)?\/?$/.test(new URL(safe).pathname)) {
      throw new Error("Use the existing Google Docs document link for each saved document.");
    }
    links[key] = safe;
  }
  return links;
}

export function deliveryToolLinks(data, section) {
  const sources = deliverySourceLinks(data.sourceLinks);
  const links = section === "Intake" ? [{ label: "Open in Google Docs", url: sources.intake }]
    : section === "Keyword evidence" ? [{ label: "Open research in Google Docs", url: sources.research }]
    : section === "SEO & checks" ? data.articles.map((article) => ({ label: `${article.location} SEO in WordPress`, url: article.link }))
    : section === "Handoff" ? [{ label: "Open in Jira", url: data.handoff.link }, { label: "Open final report in Google Docs", url: sources.report }]
    : [];
  return links.filter((link) => deliveryLink(link.url)).map((link) => ({ ...link, url: deliveryLink(link.url) }));
}

export function parseDeliveryBundle(text) {
  if (typeof text !== "string" || text.length > 500000) throw new Error("Choose a results file smaller than 500 KB.");
  let data;
  try { data = JSON.parse(text); } catch { throw new Error("This results file could not be read."); }
  if (data.schemaVersion !== 1 || !data.title?.trim() || !data.client?.trim()) throw new Error("The results need a title and client brief.");
  if (!Array.isArray(data.articles) || !data.articles.length || data.articles.length > 10) throw new Error("Include the complete article drafts in this review pack.");
  for (const article of data.articles) {
    if (!article.location || !article.title || !article.body || article.body.length < 1000
        || !Number.isInteger(article.words) || article.words < 300 || article.status !== "draft") {
      throw new Error("Each article must contain its full body, verified word count and unpublished draft status.");
    }
    if (!article.verification?.at || !article.verification?.source) throw new Error("Include the article readback source and time.");
    if (!article.seo?.title || !article.seo?.description || !article.seo?.focusKeyword || !article.seo?.verifiedAt) {
      throw new Error("Include the saved SEO fields and their readback time for every draft.");
    }
    if (article.link && !deliveryLink(article.link)) throw new Error("An article link is unsafe or contains access information.");
  }
  if (!Array.isArray(data.keywords?.rows) || !data.keywords.rows.length) throw new Error("Include the returned keyword evidence.");
  if (data.keywords.rows.some((row) => !row.keyword || !Number.isInteger(row.volume) || row.volume < 0)) throw new Error("Keyword volumes must be the returned nonnegative monthly search estimates.");
  if (!data.images?.outcome || !data.images?.checkedAt) throw new Error("Include the actual image-check outcome, including any unexecuted optimization.");
  if (!data.handoff?.summary || !deliveryLink(data.handoff?.link)) throw new Error("Include the verified handoff and its destination.");
  if (data.sourceLinks) data.sourceLinks = deliverySourceLinks(data.sourceLinks);
  // Store only the delivery schema. An import cannot create an executed run,
  // alter provider receipts, enable a connection, or inject execution options.
  return Object.fromEntries(["schemaVersion", "title", "client", "agency", "summary", "preparedAt", "brief", "intake", "keywords", "articles", "onPage", "images", "measurements", "handoff", "execution", "feedback", "sourceLinks"].map((key) => [key, data[key]]));
}

export function deliveryMetrics(data) {
  return [
    { value: data.articles.length, label: "unpublished article drafts" },
    { value: data.keywords.rows.length, label: "real keyword ideas" },
    { value: data.articles.length * 3, label: "saved SEO fields verified" },
  ];
}

export function deliverySections(data) {
  return [
    ["Client brief", `${data.client}\n${data.brief.goal}\nAudience: ${data.brief.audience}\nServices: ${data.brief.services.join(", ")}\nAreas: ${data.brief.areas.join(", ")}`],
    ["Keyword evidence", `${data.keywords.source}\n${data.keywords.targeting}\nRetrieved: ${data.keywords.retrievedAt}\nPrimary: ${data.keywords.primary}\n${data.keywords.reason}\n${data.keywords.rows.map((r) => `${r.keyword}: ${r.volume} searches/month; Ads competition ${r.competition}; index ${r.index}; low/high bid micros ${r.bidLowMicros ?? "not returned"} / ${r.bidHighMicros ?? "not returned"}`).join("\n")}\n${data.keywords.notes.join("\n")}`],
    ...data.articles.flatMap((article) => [
      [`${article.location} — unpublished draft`, `${article.title}\n${article.words} words. ${article.angle}\n${article.body}\nReadback: ${article.verification.source}, ${article.verification.at}`],
      [`${article.location} — verified saved SEO`, `Title: ${article.seo.title}\nDescription: ${article.seo.description}\nFocus keyword: ${article.seo.focusKeyword}\nRead back: ${article.seo.verifiedAt}`],
    ]),
    ["Image checks", `${data.images.outcome}\n${data.images.detail}\n${data.images.statistics}\nChecked: ${data.images.checkedAt}`],
    ["Measurements", data.measurements.map((item) => `${item.label}: ${item.status}. ${item.detail}`).join("\n")],
    ["Handoff", `${data.handoff.summary}\n${data.handoff.link}`],
    ["Execution record", Object.entries(data.execution).map(([key, items]) => `${key}:\n${items.join("\n")}`).join("\n\n")],
    ["Agency feedback", data.feedback.map((question, index) => `${index + 1}. ${question}`).join("\n")],
  ];
}
