import { crawlResult } from "./seoAuditResult.mjs";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const seoAuditDemoRoute = (runId) => uuid.test(String(runId)) ? `/runs/${runId}/demo/seo-audit` : null;
const normalize = (value) => {
  try { const url = new URL(value); url.hash = ""; return url.href; } catch { return ""; }
};

// These are authored scenario values, never provider responses. Client URLs and
// source rows are resolved at runtime from a workspace-authorized crawl. No
// customer exports, run IDs, credentials or vendor report URLs ship in this file.
export function buildSeoAuditDemo(sourceRun, inventory) {
  const crawl = crawlResult(sourceRun);
  if (!crawl || !seoAuditDemoRoute(sourceRun?.id) || !inventory.length) {
    throw new Error("Open a saved Screaming Frog export analysis with its original CSV attachments to preview this demo.");
  }
  const html = inventory.filter((row) => row["Status Code"] === "200" && /text\/html/i.test(row["Content Type"] || ""));
  const articles = html.filter((row) => { try { return new URL(row.Address).pathname.startsWith("/articles/") && new URL(row.Address).pathname !== "/articles/"; } catch { return false; } });
  const byPath = new Map(html.map((row) => [new URL(row.Address).pathname, row]));
  const mapped = (path) => {
    const row = byPath.get(path);
    return { url: row ? normalize(row.Address) : "", csv_row: row?.csv_row ?? null };
  };
  const keywordRows = [
    ["title loan help texas", 720, 31, 28, 34, "/"],
    ["how to get out of a title loan", 2400, 42, 37, 43, "/articles/where-to-get-title-loan-help"],
    ["title loan buyout texas", 320, 24, 18, 23, "/articles/title-loan-buyout-process-step-by-step"],
    ["refinance title loan", 1600, 46, 46, 39, "/articles/title-loan-refinance-buyout"],
    ["negotiate title loan payoff", 390, 27, 19, 25, "/articles/how-to-negotiate-with-title-loan-lender"],
    ["stop title loan repossession texas", 260, 29, 24, 31, "/articles/behind-on-title-loan-repossession"],
    ["title loan payoff amount", 480, 22, 14, 18, "/articles/title-loan-payoff-amount"],
    ["sell a car with a title loan", 880, 36, 41, 38, "/articles/sell-car-with-title-loan"],
    ["title loan lower monthly payment", 210, 21, 31, 36, "/articles/title-loan-refinance-lower-monthly-payment"],
    ["are title loans legal in texas", 1300, 48, 52, 58, "/articles/is-my-title-loan-legal"],
    ["ayuda con préstamos de título texas", 170, 23, 57, 64, "/es/"],
    ["salir de préstamo sobre título", 140, 18, 63, 69, "/es/articles/where-to-get-title-loan-help"],
  ].map(([keyword, volume, difficulty, position, previous, path]) => ({ keyword, volume, difficulty, position, previous, change: previous - position, ...mapped(path), simulated: true }));
  const competitors = [
    { domain: "texas-title-help.example", keywords: 186, traffic: 740, shared: 14, missing: 32 },
    { domain: "auto-loan-relief.example", keywords: 312, traffic: 1260, shared: 19, missing: 47 },
    { domain: "title-payoff-guide.example", keywords: 94, traffic: 380, shared: 9, missing: 21 },
  ];
  const backlinks = [
    ["texas-consumer-guide.example/resources", 31, "title loan help", true, "Live", "/"],
    ["community-money.example/vehicle-debt", 24, "loan payoff guide", true, "Live", "/articles/title-loan-payoff-amount"],
    ["local-services.example/auto-finance", 18, "website", false, "Live", "/"],
    ["budget-journal.example/title-loan-options", 27, "refinancing options", true, "Live", "/articles/title-loan-refinance-buyout"],
    ["regional-directory.example/businesses", 12, "company profile", false, "Live", "/"],
    ["money-resource.example/texas", 9, "title loan support", true, "Lost", "/"],
  ].map(([source, rating, anchor, follow, status, path]) => ({ source: `https://${source}`, rating, anchor, follow: follow ? "Follow" : "Nofollow", status, target: mapped(path).url, csv_row: mapped(path).csv_row, simulated: true }));
  const actual = (id) => crawl.issues?.find((issue) => issue.id === id)?.affected || [];
  const orphanRows = articles.slice(0, 2).map((row) => ({ url: normalize(row.Address), csv_row: row.csv_row }));
  const languageRows = html.filter((row) => new URL(row.Address).pathname.startsWith("/es/articles/")).slice(0, 6).map((row) => ({ url: normalize(row.Address), csv_row: row.csv_row }));
  const blankDescriptions = html.filter((row) => !(row["Meta Description 1"] || "").trim()).map((row) => ({ url: normalize(row.Address), csv_row: row.csv_row }));
  const hints = [
    { id: "SB01", priority: "High", title: "Canonical points to a redirect", affected: actual("T01"), basis: "Scenario derived from the real Screaming Frog canonical rows. No independent Sitebulb verification." },
    { id: "SB02", priority: "Medium", title: "Redirecting internal URL variants", affected: actual("T02"), basis: "Scenario derived from the real crawl redirects. A 307 is not automatically an error." },
    { id: "SB03", priority: "Medium", title: "Potential orphan articles", affected: orphanRows, basis: "Hypothetical Sitebulb finding. The supplied crawl has no valid link-edge export and cannot verify orphan status." },
    { id: "SB04", priority: "Medium", title: "Potential missing reciprocal language links", affected: languageRows, basis: "Hypothetical Sitebulb finding. Hreflang was not established by the supplied exports." },
    { id: "SB05", priority: "Low", title: "Blank meta descriptions", affected: blankDescriptions, basis: "Scenario derived from the real CSV description fields; no independent Sitebulb crawl." },
  ].map((hint) => ({ ...hint, simulated: true }));
  const tools = [
    { key: "semrush", name: "Semrush", label: "Simulated output", state: "simulated", simulated: true, message: "42 organic keywords · 96 estimated visits/month · illustrative US database scenario", metrics: [{ label: "Organic keywords", value: 42 }, { label: "Estimated visits / month", value: 96 }, { label: "Authority Score", value: 16 }], keywords: keywordRows, competitors, actions: [] },
    { key: "ahrefs", name: "Ahrefs", label: "Simulated output", state: "simulated", simulated: true, message: "38 organic keywords · 84 estimated visits/month · 44 referring domains · illustrative scenario", metrics: [{ label: "Domain Rating", value: 12 }, { label: "Referring domains", value: 44 }, { label: "Backlinks", value: 96 }], visibility: [{ month: "May", traffic: 42 }, { month: "Jun", traffic: 51 }, { month: "Jul", traffic: 63 }, { month: "Aug", traffic: 72 }, { month: "Sep", traffic: 79 }, { month: "Oct", traffic: 84 }], backlinks, actions: [] },
    { key: "sitebulb", name: "Sitebulb", label: "Simulated output", state: "simulated", simulated: true, message: `${hints.length} illustrated hint groups · ${crawl.counts.url_records} URLs used as the scenario scope · no Sitebulb crawl performed`, metrics: [{ label: "Example audit score", value: "71 / 100" }, { label: "Hint groups", value: hints.length }, { label: "Scope from real crawl", value: crawl.counts.url_records }], hints, actions: [] },
  ];
  const observed = (crawl.issues || []).filter((issue) => ["T01", "T02", "L01", "C02"].includes(issue.id)).map((issue) => ({
    ...issue, kind: issue.state, affected_csv_rows: issue.affected.map((row) => row.csv_row),
    evidence: `REAL Screaming Frog CSV: ${issue.affected.length} affected URL records. ${issue.reasoning}`,
    expert_review: issue.id === "C02" ? "SEO editor; snippet widths are heuristics, not Google limits." : "SEO and engineering review of the original rows and a fresh crawl.",
    acceptance: "Verify the agreed change in a fresh crawl; compare affected URLs with the preserved source rows.",
  }));
  const proposed = (id, group, title, rows, evidence, fix, effort, dependencies, reasoning, expert_review, acceptance) => ({
    id, priority: "P2", group, kind: "Simulated recommendation", title,
    affected_csv_rows: [...new Set(rows.map((row) => row.csv_row).filter(Number.isInteger))],
    evidence: `SIMULATED: ${evidence}`, fix, effort, dependencies, reasoning, expert_review, acceptance,
  });
  const backlog = [...observed,
    proposed("C01", "Content", "Map purchase-intent queries to existing pages", keywordRows.filter((row) => row.position >= 14 && row.position <= 31), "Semrush scenario keyword rows; positions and volumes are illustrative.", "Validate a live keyword baseline, then match service intent to the mapped landing pages and calls to action.", "4–6 content hours (provisional)", "Confirmed business goals; real keyword data; T01 URL policy", "In the scenario, mid-ranking intent-led pages are a practical next optimisation scope.", "Financial services content and SEO specialist", "Replace demo positions with a real baseline and measure agreed lead events."),
    proposed("L02", "Internal linking", "Review navigation from topic hubs to priority articles", keywordRows.filter((row) => row.csv_row), "Mapped real article URLs with synthetic keyword priorities; source link edges are missing.", "Obtain actual source/destination links, review the topic hubs and add relevant links after confirming the preferred URLs.", "2–4 hours plus QA (provisional)", "T01; valid All Inlinks export; C01", "Use the simulated demand priorities to demonstrate a navigation task without claiming actual missing links.", "SEO and content editor", "Verify each proposed source link and target returns 200 in a fresh crawl."),
    proposed("T03", "Technical SEO", "Check reciprocal language annotations", languageRows, "Sitebulb scenario SB04; missing hreflang is hypothetical.", "Inspect these EN/ES page pairs and verify reciprocal hreflang and canonical alignment before any edit.", "2–3 diagnostic hours (provisional)", "Actual rendered HTML; language policy; T01", "A validation task is appropriate until the hypothetical hint is confirmed.", "International SEO specialist", "Record actual annotations and expected alternate URLs for each inspected pair."),
    proposed("L03", "Internal linking", "Validate the illustrative orphan-page finding", orphanRows, "Sitebulb scenario SB03; orphan status is unverified.", "Compare a full crawl link graph with sitemap, analytics and known URL sources before proposing navigation changes.", "1–2 diagnostic hours (provisional)", "Completed Sitebulb audit or valid link graph; URL discovery sources", "The current Screaming Frog aggregates cannot prove orphan status.", "Technical SEO specialist", "Confirm or dismiss each scenario URL using actual inbound link edges."),
    proposed("B01", "Backlinks", "Review link relevance and a lost-link recovery candidate", backlinks.filter((row) => row.status === "Lost"), "Ahrefs scenario: 44 referring domains and six fictional sample links, including one lost example.", "Replace every fictional domain with a real export, inspect lost links and review relevance before any outreach.", "2–4 research hours after real data (provisional)", "Verified Ahrefs/Semrush backlink data; link policy", "Demonstrates a backlink review task; no link is labelled toxic and no disavow is proposed.", "Off-page SEO specialist", "Attach verified source URLs and evidence; obtain separate approval for any outreach."),
    proposed("C03", "Content", "Validate competitor coverage and financial claims", keywordRows.filter((row) => /legal|payoff|negotiate/.test(row.keyword)), "Semrush scenario competitors are fictional .example domains; no competitive gap is established.", "Identify actual competing pages, check search intent, and review legal or financial claims with a qualified expert.", "3–5 research/editor hours (provisional)", "Confirmed market and goals; real competitor evidence", "The sample demonstrates how an evidence-led content gap would enter the backlog.", "Qualified financial/legal reviewer and Spanish-language editor", "Record real competing URLs, supported claims and approved wording before publishing."),
  ];
  return {
    simulated: true, scenarioDate: "2026-10-19", sourceRun, tools,
    manifest: { backlog, references: [{ key: "crawl", name: "Screaming Frog", runId: sourceRun.id }], sourceNotes: {
      intake: `Website: ${crawl.website}, from the supplied crawl. Current Mantas Auk engagement and owner goals remain unconfirmed. Scenario goal: qualified Texas auto-loan-exit/title-payoff enquiries in English and Spanish. Proposed destination names: Google Docs for reporting and Jira for tasks; confirm the workspace connections and Jira project before real delivery. This preview creates no documents, tickets or website changes.`,
    } },
    checks: [
      "Semrush, Ahrefs and Sitebulb outputs are authored demo data, not vendor responses. Their snapshot date is an illustrative scenario date, not an export date.",
      "Semrush shows 42 keywords / 96 visits; Ahrefs shows 38 / 84. This illustrates different vendor coverage and estimates, not an observed disagreement or measured traffic.",
      "Sitebulb canonical and redirect counts reuse the real Screaming Frog scope. They do not constitute independent corroboration. Orphan and hreflang examples are hypothetical.",
      "Competitor and referring domains ending in .example are fictional. No outreach, disavow, Jira issue, Google Doc or website modification is performed.",
    ],
  };
}
