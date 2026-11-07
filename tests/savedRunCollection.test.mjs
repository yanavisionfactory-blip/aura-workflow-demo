import test from "node:test";
import assert from "node:assert/strict";
import { parseRunCollection, collectionActivity } from "../src/lib/savedRunCollection.mjs";
import { preferredToolOutcome } from "../src/lib/toolResultViews.mjs";
import { primaryResultFromOutputs } from "../src/lib/resultPresentation.mjs";
import { savedToolResponse } from "../src/lib/savedToolResponse.mjs";
const runId = "11111111-1111-4111-8111-111111111111", stepId = "22222222-2222-4222-8222-222222222222";
const collection = { kind: "saved_run_collection", title: "Ad performance", sources: [{ runId, stepIds: [stepId] }] };
test("collections keep only validated references and require completed receipts from the exact accessible run", () => {
  assert.deepEqual(parseRunCollection({ ...collection, forgedResult: { revenue: 9000 } }), collection);
  assert.throws(() => parseRunCollection({ ...collection, sources: [{ runId: "https://other.example/", stepIds: [stepId] }] }));
  assert.throws(() => collectionActivity(collection, []));
  const run = { id: runId, steps: [{ id: stepId, key: "read", status: "pending", tool_slug: "google-ads", output: { provider_result: { ret: [] } } }] };
  assert.throws(() => collectionActivity(collection, [run]));
  run.steps[0].status = "completed";
  assert.equal(collectionActivity(collection, [run])[0].runId, runId);
  assert.equal(collectionActivity(collection, [run])[0].id, `${runId}:${stepId}`);
});
const canva = (items, query = "Campaign review") => ({ id: "canva-read", key: "canva-read", status: "completed", output: {
  operation: "canva.list-designs", resolved_arguments: { query }, critic: { action: "accept" }, outcome_check: { status: "verified" },
  provider_result: { os: [], ret: { items }, exports: { $summary: "Retrieved designs" } },
} });
const design = { id: "matching", title: "Campaign review", page_count: 1, urls: { edit_url: "https://www.canva.com/api/design/signed/edit" }, thumbnail: { url: "https://media.canva.com/thumbnail" } };
test("exact broker Canva readback leads Sheets and retains the provider URL and source", () => {
  const result = preferredToolOutcome({ kind: "spreadsheet", spreadsheetId: "sheet" }, [canva([{ id: "unrelated", title: "Other" }, design])]);
  assert.equal(result.provider, "Canva"); assert.equal(result.designId, "matching");
  assert.equal(result.link, design.urls.edit_url); assert.equal(result.pageCount, 1); assert.equal(result.sourceStepId, "canva-read");
  assert.equal(result.providerVerb, "Reused from");
});
test("ambiguous, unrelated and pending Canva results never become a finished slide", () => {
  for (const entry of [canva([design, { ...design, id: "second" }]), canva([design], "Different"), canva([design], "")]) {
    assert.notEqual(primaryResultFromOutputs([entry.output]).kind, "presentation");
  }
  assert.notEqual(primaryResultFromOutputs([{ operation: "canva.create-design-import-job", provider_result: { ret: { job: { status: "in_progress", id: "job" } } } }]).kind, "presentation");
});
test("ad summaries preserve missing metrics, conversions, zeroes and exact account scope", () => {
  const empty = savedToolResponse({ tool: "Meta Ads", inputs: {}, response: { account_id: "act_test", account: { currency: "EUR", timezone_name: "Europe/Berlin" }, date_range: { since: "2025-01-01", until: "2025-12-31" }, data: [], complete: true } });
  assert.equal(empty.empty, true); assert.match(empty.summary, /unavailable, not zero/);
  assert.equal(empty.facts.find((f) => f.label === "Account").value, "act_test");
  const google = savedToolResponse({ tool: "Google Ads", inputs: { accountId: "customer-test" }, response: { ret: [{ campaign: { name: "Test" }, metrics: { costMicros: "12000000", clicks: "0", impressions: "100", conversions: "0" } }] } });
  const metrics = Object.fromEntries(google.campaigns[0].metrics.map((m) => [m.label, m.value]));
  assert.equal(metrics.Spend, "12"); assert.equal(metrics.Clicks, "0"); assert.equal(metrics.CPC, "Unavailable"); assert.equal(metrics["Conversion value"], "Unavailable");
});
