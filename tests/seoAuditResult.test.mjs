import test from "node:test";
import assert from "node:assert/strict";
import { seoAuditManifest, providerOutcome, providerResultLink, crawlInventory, mappedBacklog, parseCsv, crawlResult } from "../src/lib/seoAuditResult.mjs";
import { primaryResultFromOutputs } from "../src/lib/resultPresentation.mjs";

const ids = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"];
const columns = ["id", "priority", "group", "kind", "title", "affected_csv_rows", "evidence", "fix", "effort", "dependencies", "reasoning", "expert_review", "acceptance"];
const row = (id = "T01", priority = "P1", scope = [2, 3]) => [id, priority, "Technical SEO", "Observed", "Canonical conflict", scope, "Two source rows", "Align signals", "2 hours", "Confirm URL policy", "Conflicting signals", "SEO expert", "Recrawl"];
const packet = () => [
  { id: "CRAWL", content: `Saved https://aura.example/runs/${ids[0]} .` },
  { id: "BACKLOG", content: JSON.stringify({ columns, rows: [row()] }) },
  { id: "TOOLS", content: `Semrush: blocked. Saved https://aura.example/runs/${ids[1]} . Ahrefs: blocked. Saved https://aura.example/runs/${ids[2]} . Sitebulb: connection blocked, no export.` },
  { id: "INTAKE", content: "Client and goals unconfirmed. No site changes." },
];
const output = (sources, synthetic = false) => ({ operation: "report.compose", critic: { action: "accept" }, outcome_check: { status: "verified" }, provider_result: { status: "draft", body: "Saved review", title: "Audit", sources, synthetic } });

test("saved typed SEO packet becomes a native result without a document body or document link", () => {
  const result = primaryResultFromOutputs([output(packet())]);
  assert.equal(result.kind, "seo_audit");
  assert.equal(result.preview, undefined);
  assert.equal(result.link, null);
  assert.deepEqual(result.audit.references.map((ref) => ref.runId), ids);
  assert.equal(result.audit.sourceNotes.sitebulb, "connection blocked, no export.");
});

test("normal and synthetic reports keep their existing result view", () => {
  assert.equal(primaryResultFromOutputs([output([{ id: "CRAWL", content: "SEO keywords only" }])]).kind, "report");
  assert.equal(primaryResultFromOutputs([output(packet(), true)]).kind, "report");
});

test("malformed packets cannot opt into the native view or supply an API path", () => {
  const cases = [
    (sources) => { sources[1].content = "not json"; },
    (sources) => { sources[0].content = "https://aura.example/runs/../../connections"; },
    (sources) => { sources[1].content = JSON.stringify({ columns, rows: [row("T01", "P1", [-1])] }); },
    (sources) => { sources[1].content = JSON.stringify({ columns, rows: [row("T01", "P0")] }); },
    (sources) => { sources[1].content = JSON.stringify({ columns, rows: [["too short"]] }); },
  ];
  for (const change of cases) { const sources = packet(); change(sources); assert.equal(seoAuditManifest(sources), null); }
});

test("actual Semrush MCP access error remains blocked even when step status says completed", () => {
  const run = { steps: [{ status: "completed", operation: "domain_overview", arguments: { domain: "example.org", api_key: "secret" }, output: { provider_result: { is_error: true, content: [{ type: "text", text: JSON.stringify({ code: "no_api_units", message: "Insufficient API units" }) }] } } }, { status: "awaiting_approval", operation: "execute_report" }] };
  const result = providerOutcome(run, "Semrush");
  assert.equal(result.state, "blocked");
  assert.equal(result.code, "no_api_units");
  assert.equal(result.message, "Insufficient API units");
  assert.equal(result.actions[0].inputs.api_key, "[redacted]");
  assert.equal(result.actions[1].hasResponse, false);
  assert.equal(result.actions[1].status, "awaiting_approval");
});

test("Ahrefs plan error exposes the actual HTTP status and redacts embedded debug cookies", () => {
  const run = { steps: [{ status: "completed", operation: "ahrefs.get-backlinks-one-per-domain", output: { provider_result: { error: { response: { status: 403, data: { error: "Insufficient plan" } } }, os: [{ message: '[debug] {"cookie":"private-cookie","status":403}' }] } } }] };
  const result = providerOutcome(run, "Ahrefs");
  assert.equal(result.code, "403");
  assert.equal(result.message, "Insufficient plan");
  assert.equal(result.state, "blocked");
  assert.ok(!JSON.stringify(result.actions).includes("private-cookie"));
  assert.equal(providerOutcome(null, "Ahrefs").state, "unavailable");
});

test("no external tool result is invented from an error, debug link or account URL", () => {
  const run = (result) => ({ steps: [{ output: { provider_result: result } }] });
  assert.equal(providerResultLink(run({ is_error: true, report_url: "https://semrush.example/report/1" })), null);
  assert.equal(providerResultLink(run({ url: "https://semrush.example/mcp-access" })), null);
  assert.equal(providerResultLink(run({ report_url: "javascript:alert(1)" })), null);
  assert.equal(providerResultLink(run({ report_url: "https://vendor.example/report?token=secret" })), null);
  assert.equal(providerResultLink(run({ report_url: "https://vendor.example/report/123" })), "https://vendor.example/report/123");
});

test("CSV preserves quoted commas, newlines, escaped quotes, Unicode and physical record mapping", () => {
  const csv = '\uFEFFAddress,Canonical Link Element 1,Status Code,Title 1\r\nhttps://example.org/a,https://example.org/a.html,200,"A, \'quoted\' title"\r\nhttps://example.org/b,,307,"Line one\nLine ""two"" ñ"\r\n';
  assert.equal(parseCsv(csv)[2][3], 'Line one\nLine "two" ñ');
  const document = { name: "misleading-name.csv", file_url: `data:text/csv;base64,${Buffer.from(csv).toString("base64")}` };
  const inventory = crawlInventory({ inputs: { attached_documents: [document, document] } }, (data) => Buffer.from(data, "base64").toString("utf8"));
  assert.equal(inventory.length, 2); // Duplicate attachment is not a second inventory.
  assert.deepEqual(inventory.map((record) => record.csv_row), [2, 3]);
  const tasks = mappedBacklog([Object.fromEntries(columns.map((col, i) => [col, row("T02", "P2", [3])[i]])), Object.fromEntries(columns.map((col, i) => [col, row()[i]]))], inventory);
  assert.equal(tasks[0].id, "T01");
  assert.equal(tasks[0].affected[1].url, "https://example.org/b");
  assert.equal(tasks[1].affected[0].url, "https://example.org/b"); // Overlap retained as evidence, never summed into unique URLs.
});

test("unreadable source mappings remain unresolved, without substituting guessed URLs", () => {
  assert.deepEqual(crawlInventory({ inputs: { attached_documents: [{ file_url: "https://external.example/secret.csv" }] } }, () => { throw Error("must not fetch"); }), []);
  const task = mappedBacklog([{ id: "T01", priority: "P1", affected_csv_rows: [5] }], [])[0];
  assert.equal(task.affected[0].csv_row, 5);
  assert.equal(task.affected[0].url, "");
  assert.equal(crawlResult({ steps: [{ operation: "report.compose", output: { provider_result: { source_tool: "Screaming Frog" } } }] }), null);
});
