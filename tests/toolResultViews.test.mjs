import test from "node:test";
import assert from "node:assert/strict";
import { mainToolEntry, toolResultEntries, toolResultGroups } from "../src/lib/toolResultViews.mjs";
import { supportingReceipts } from "../src/lib/resultPresentation.mjs";

const report = (id, body) => ({ id, key: id, status: "completed", tool: "AURA", action: `Prepare ${id}`,
  output: { operation: "report.compose", critic: { action: "accept" }, outcome_check: { status: "verified" },
    provider_result: { status: "draft", title: id, body, synthetic: true, sources: [] } },
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
