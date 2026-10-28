import test from "node:test";
import assert from "node:assert/strict";
import { mainToolEntry, supportingToolOutputs, toolResultEntries, toolResultGroups } from "../src/lib/toolResultViews.mjs";
import { primaryResultFromOutputs, supportingReceipts } from "../src/lib/resultPresentation.mjs";
import { toolEvidence } from "../src/lib/toolEvidence.mjs";

const report = (id, body) => ({ id, key: id, status: "completed", tool: "AURA", action: `Prepare ${id}`,
  output: { operation: "report.compose", critic: { action: "accept" }, outcome_check: { status: "verified" },
    provider_result: { status: "draft", title: id, body, synthetic: true, sources: [] } },
});

test("public website reads are attributed to web research while composition remains ChatGPT", () => {
  const entries = toolResultEntries([{ id: "page", tool: "AURA Intelligence", status: "completed",
    output: { operation: "web.page.read", provider_result: { url: "https://example.com/", text: "Retrieved content" } } }, report("analysis", "Comparison")]);
  assert.deepEqual(entries.map((entry) => entry.tool), ["Web research", "ChatGPT"]);
});

test("main output identity retains other actions from the same tool without duplicating the main report", () => {
  const activity = [report("first", "Full first report."), report("main", "Full final report.")];
  const entries = toolResultEntries(activity);
  const primary = entries[1].preview;
  const main = mainToolEntry(entries, primary, null);
  assert.equal(main.id, "main");
  assert.equal(toolResultGroups(entries)[0].tool, "ChatGPT");
  assert.equal(toolResultGroups(entries)[0].entries.length, 2);
  const receipts = supportingReceipts({}, activity, primary, null, main.id);
  assert.deepEqual(receipts.map((item) => item.actionId), ["first"]);
  assert.deepEqual(supportingReceipts({ outcomes: [{ title: "Saved result" }] }, [activity[1]], primary, null, main.id), []);
});

test("report prose naming platforms cannot fabricate provider actions or change a synthetic processor's tool", () => {
  const activity = [report("review", "Google Ads, Meta Ads, Mailchimp and Klaviyo proposed work."), {
    id: "source", key: "source", tool: "aura", action: "Process supplied Google export", status: "completed",
    output: { operation: "weekly.source.analyze", provider_result: { synthetic: true,
      source: { name: "Google Ads", rows: [] }, receipt: { provider_api_called: false } } },
  }];
  const entries = toolResultEntries(activity);
  assert.equal(entries.length, 2);
  assert.deepEqual(toolResultGroups(entries).map((group) => group.tool), ["ChatGPT", "AURA Intelligence"]);
  assert.equal(entries[1].source.name, "Google Ads");
  assert.equal(entries[1].response.receipt.provider_api_called, false);
  assert.equal(entries[1].synthetic, true);
});

test("failed, missing and empty provider responses stay distinct, and secrets stay redacted", () => {
  const entries = toolResultEntries([
    { id: "missing", tool: "google-ads", status: "blocked", error: "Account access is missing" },
    { id: "empty", tool: "meta-ads", status: "completed", output: { provider_result: [] } },
    { id: "error", tool: "mailchimp", status: "completed", output: { provider_result: {
      error: "Read failed", access_token: "secret-value", body: "Do not promote this as a saved draft." } } },
  ]);
  assert.equal(entries[0].hasResponse, false);
  assert.equal(entries[0].error, "Account access is missing");
  assert.equal(entries[1].hasResponse, true);
  assert.deepEqual(entries[1].response, []);
  assert.equal(entries[2].status, "provider_error");
  assert.equal(entries[2].preview, null);
  assert.equal(entries[2].response.access_token, "[redacted]");
  assert.doesNotMatch(JSON.stringify(entries), /secret-value/);
});

test("unknown primary identity does not silently select an unrelated first tool", () => {
  const entries = toolResultEntries([{ id: "keywords", tool: "google-ads", status: "completed",
    output: { provider_result: { ret: [{ keyword: "coffee" }] } } }]);
  assert.equal(mainToolEntry(entries, {}, null), undefined);
});

test("Claude fallback remains one selected-tool output with honest execution details; Sheets leads results", () => {
  const activity = [
    { id: "draft", key: "draft", status: "completed", tool: "aura", action: "Prepare KPI comparison", output: {
      step_id: "draft", operation: "intelligence.claude_backup", critic: { action: "accept" }, outcome_check: { status: "verified" },
      fallback: { status: "used", requested_tool: "anthropic", requested_operation: "anthropic.chat",
        actual_tool: "aura", actual_operation: "intelligence.claude_backup",
        message: "Claude had insufficient API credits. AURA Intelligence completed this step." },
      provider_result: { ret: { content: [{ type: "text", text: "# September 2026\nRevenue | Target | Actual" }] } },
    } },
    { id: "sheet", status: "completed", tool: "Google Sheets", output: { step_id: "sheet", operation: "sheets.append",
      provider_result: { spreadsheetId: "test-id", updates: { updatedRange: "KPIs!A1:C2" } },
      critic: { action: "accept" }, outcome_check: { status: "verified", observed: { range: "KPIs!A1:C2", values: [["Metric", "Target", "Actual"], ["Revenue", "", ""]] } },
    } },
  ];
  const entries = toolResultEntries(activity);
  assert.deepEqual(entries.map((entry) => entry.tool), ["Claude", "Google Sheets"]);
  assert.equal(entries[0].actualTool, "AURA Intelligence");
  assert.equal(toolEvidence(activity)[0].tool, "AURA Intelligence");
  assert.match(entries[0].backupNotice, /insufficient API credits/);
  assert.equal(entries[0].preview.displayProvider, "Claude");
  assert.equal(entries[0].preview.provider, "AURA Intelligence");
  const primary = primaryResultFromOutputs(activity.map((step) => step.output));
  assert.equal(primary.kind, "spreadsheet");
  assert.equal(mainToolEntry(entries, primary).tool, "Google Sheets");
  assert.deepEqual(supportingToolOutputs(entries, primary).map((group) => group.tool), ["Claude"]);
  const withoutReceipt = structuredClone(activity[0]);
  delete withoutReceipt.output.fallback;
  assert.equal(toolResultEntries([withoutReceipt])[0].tool, "AURA Intelligence");
});
