import test from "node:test";
import assert from "node:assert/strict";
import { buildSeoAuditDemo, seoAuditDemoRoute } from "../src/lib/seoAuditDemo.mjs";
import { mappedBacklog, providerOutcome } from "../src/lib/seoAuditResult.mjs";

const id = "11111111-1111-4111-8111-111111111111";
function fixture() {
  const inventory = ["/", "/es/", "/articles/title-loan-payoff-amount", "/articles/title-loan-refinance-buyout", "/es/articles/where-to-get-title-loan-help"].map((path, index) => ({ Address: `https://client.example${path}`, csv_row: index + 2, "Status Code": "200", "Content Type": "text/html", "Meta Description 1": index === 3 ? "" : "Description" }));
  const affected = [{ url: inventory[2].Address, csv_row: 4, canonical: `${inventory[2].Address}.html` }];
  const crawl = { source_tool: "Screaming Frog", website: "https://client.example/", counts: { url_records: 9, canonical_conflicts: 1 }, issues: [
    { id: "T01", priority: "P1", group: "Technical SEO", state: "Observed", title: "Canonical conflict", affected, fix: "Confirm policy", effort: "2h", dependencies: "Owner decision", reasoning: "Real CSV rows" },
    { id: "T02", priority: "P2", group: "Technical SEO", state: "Review", title: "Redirect review", affected, fix: "Check redirect", effort: "1h", dependencies: "T01", reasoning: "307 alone is not an error" },
    { id: "L01", priority: "P2", group: "Internal linking", state: "Observed", title: "Links to redirects", affected, fix: "Get link edges", effort: "2h", dependencies: "T01", reasoning: "Source pages unknown" },
    { id: "C02", priority: "P3", group: "Content", state: "Heuristic review", title: "Snippet review", affected, fix: "Check intent", effort: "2h", dependencies: "Goals", reasoning: "Widths are heuristics" },
  ], warnings: ["No link-edge export"], files: [{ filename: "internal.csv", sha256: "source-hash" }] };
  const run = { id, status: "completed", inputs: { attached_documents: [{ name: "internal.csv", file_url: "data:text/csv,original" }] }, steps: [{ key: "crawl", operation: "seo.crawl.analyze", output: { operation: "seo.crawl.analyze", provider_result: crawl } }] };
  return { inventory, run, crawl };
}

test("demo keeps the real crawl unchanged and does not manufacture executed provider receipts", () => {
  const { inventory, run, crawl } = fixture();
  const original = JSON.stringify(run);
  const demo = buildSeoAuditDemo(run, inventory);
  assert.equal(JSON.stringify(run), original);
  assert.equal(demo.sourceRun.steps[0].output.provider_result, crawl);
  assert.deepEqual(demo.manifest.references, [{ key: "crawl", name: "Screaming Frog", runId: id }]);
  assert.equal(demo.tools.length, 3);
  for (const tool of demo.tools) {
    assert.equal(tool.simulated, true);
    assert.equal(tool.state, "simulated");
    assert.equal(tool.label, "Simulated output");
    assert.deepEqual(tool.actions, []);
    assert.equal(tool.runId, undefined);
    assert.equal(tool.run, undefined);
    assert.equal(tool.report_url, undefined);
  }
  // Existing provider-error evidence stays an error even alongside a preview.
  assert.equal(providerOutcome({ steps: [{ status: "completed", output: { provider_result: { error: { response: { status: 403, data: { error: "Insufficient plan" } } } } } }] }, "Ahrefs").state, "blocked");
});

test("scenario resolves targets only to actual source URLs and leaves absent pages unmapped", () => {
  const { inventory, run } = fixture();
  const demo = buildSeoAuditDemo(run, inventory);
  const keywords = demo.tools[0].keywords;
  assert.equal(keywords.find((row) => row.keyword === "title loan payoff amount").csv_row, 4);
  assert.equal(keywords.find((row) => row.keyword === "how to get out of a title loan").url, "");
  const urls = new Set(inventory.map((row) => row.Address));
  for (const row of keywords) if (row.url) assert.ok(urls.has(row.url));
  for (const row of demo.tools[1].backlinks) {
    assert.ok(new URL(row.source).hostname.endsWith(".example"));
    if (row.target) assert.ok(urls.has(row.target));
  }
  for (const row of demo.tools[0].competitors) assert.ok(row.domain.endsWith(".example"));
});

test("roadmap separates observed rows from simulated recommendations and preserves scope", () => {
  const { inventory, run } = fixture();
  const demo = buildSeoAuditDemo(run, inventory);
  const backlog = mappedBacklog(demo.manifest.backlog, inventory);
  assert.equal(backlog.length, 10);
  assert.equal(backlog[0].id, "T01");
  assert.match(backlog[0].evidence, /^REAL Screaming Frog CSV:/);
  assert.equal(backlog[0].affected[0].url, inventory[2].Address);
  for (const task of backlog.filter((item) => item.kind === "Simulated recommendation")) {
    assert.match(task.evidence, /^SIMULATED:/);
    for (const key of ["fix", "effort", "dependencies", "reasoning", "expert_review", "acceptance"]) assert.ok(task[key]);
    for (const row of task.affected) assert.ok(inventory.some((source) => source.csv_row === row.csv_row && source.Address === row.url));
  }
  const hints = demo.tools[2].hints;
  assert.equal(hints[0].affected.length, 1); // Uses this fixture, never the real client's hardcoded count.
  assert.match(hints.find((hint) => hint.id === "SB03").basis, /Hypothetical/);
  assert.match(demo.checks.join(" "), /do not constitute independent corroboration/);
  assert.match(demo.manifest.sourceNotes.intake, /goals remain unconfirmed/);
});

test("demo requires an accessible real crawl with original attachments and validates route IDs", () => {
  const { run } = fixture();
  assert.equal(seoAuditDemoRoute(id), `/runs/${id}/demo/seo-audit`);
  assert.equal(seoAuditDemoRoute("../../connections"), null);
  assert.equal(seoAuditDemoRoute("https://outside.example"), null);
  assert.throws(() => buildSeoAuditDemo(run, []), /original CSV/);
  assert.throws(() => buildSeoAuditDemo({ id, steps: [] }, fixture().inventory), /Screaming Frog/);
});
