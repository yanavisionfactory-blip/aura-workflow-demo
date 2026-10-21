import test from "node:test";
import assert from "node:assert/strict";
import { campaignSourceRunIds, campaignDeliveryRows, campaignApplicationGroup, campaignRunActivity, campaignActivityForGroup } from "../src/lib/campaignToolResults.mjs";
import { toolEvidence } from "../src/lib/toolEvidence.mjs";

const first = "11111111-1111-4111-8111-111111111111";
const second = "22222222-2222-4222-8222-222222222222";

test("source run references require explicit provenance and a UUID, with deduplication and a read bound", () => {
  const sources = [{ content: JSON.stringify({ native_source_run: first }) },
    { content: `Native source run ${first} completed reads. Separate native run ${second} preserves a failure.` },
    { content: JSON.stringify({ source_run_id: second }) },
    { content: JSON.stringify({ native_source_run: "../../connections" }) },
    { content: `Unrelated UUID ${first}; https://external.example/runs/${second}; successful step with invented receipt.` },
    { content: null }];
  assert.deepEqual(campaignSourceRunIds(sources), [first, second]);
  assert.deepEqual(campaignSourceRunIds(sources.slice(3)), []);
  assert.equal(campaignSourceRunIds(Array.from({ length: 12 }, (_, index) => ({ content: JSON.stringify({ source_run_id: `${String(index).padStart(8, "0")}-1111-4111-8111-111111111111` }) }))).length, 8);
});

test("delivery summaries preserve draft and blocked wording without making execution receipts", () => {
  const body = "# Application delivery status\n\n| Actual application | Action completed | Saved output/link | Remaining action |\n|---|---|---|---|\n| Google Ads | Copy prepared; no native draft saved | AURA only | Confirm account |\n| PM unconfirmed (Jira candidate) | Task drafts only | AURA only | Repair failed read |\n\n# Next section\nText";
  const rows = campaignDeliveryRows(body);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].completed, "Copy prepared; no native draft saved");
  assert.equal(rows[1].remaining, "Repair failed read");
  assert.deepEqual(campaignDeliveryRows("| Application | Complete | Link | Next |\n|---|---|---|---|\n| Test | done | link | none |"), []);
  assert.equal(campaignApplicationGroup(rows[0].application, ["Google Ads"]), "Google Ads");
  assert.equal(campaignApplicationGroup(rows[1].application, ["Project management"]), "Project management");
  assert.equal(campaignApplicationGroup(rows[1].application, ["Approvals and handoff"]), "Approvals and handoff");
  assert.equal(campaignApplicationGroup("Indoor CMS not identified", ["Indoor screens"]), "Indoor screens");
  assert.equal(campaignApplicationGroup("AURA approval bundle/external process unknown", ["Approvals"]), "Approvals");
});

test("per-application evidence uses original saved steps and preserves failures, empty responses, inputs and redaction", () => {
  const run = { steps: [
    { id: "ads", tool_slug: "google-ads", operation: "google-ads.list-account-id-options", status: "completed", arguments: {}, output: { provider_result: { ret: [{ label: "Unnamed account" }] } } },
    { id: "drive", tool_slug: "google-drive", operation: "google-drive.search-files", status: "completed", output: { provider_result: { ret: { files: [], count: 0 } } } },
    { id: "pm", tool_slug: "jira", operation: "jira.issues.search", status: "failed", arguments: { access_token: "secret", query: "client" }, error: "Connection needs attention", output: {} },
    { id: "report", tool_slug: "aura", operation: "report.compose", status: "completed", output: { provider_result: { body: "Prepared copy only" } } },
  ] };
  const activity = campaignRunActivity(run);
  assert.deepEqual(campaignActivityForGroup(activity, "Google Ads").map((step) => step.id), ["ads"]);
  assert.deepEqual(campaignActivityForGroup(activity, "Assets").map((step) => step.id), ["drive"]);
  assert.deepEqual(campaignActivityForGroup(activity, "Social ads"), []);
  assert.deepEqual(campaignActivityForGroup(activity, "Business Profile"), []);
  assert.deepEqual(campaignActivityForGroup(activity, "Approvals"), []);
  const pm = toolEvidence(campaignActivityForGroup(activity, "Project management"))[0];
  assert.equal(pm.status, "failed");
  assert.equal(pm.hasResponse, false);
  assert.equal(pm.inputs.access_token, "[redacted]");
  assert.equal(pm.error, "Connection needs attention");
  assert.deepEqual(toolEvidence(campaignActivityForGroup(activity, "Assets"))[0].response.ret.files, []);
  assert.equal(campaignActivityForGroup(activity, "Tool outputs").length, 4);
  assert.deepEqual(campaignRunActivity({ sources: [{ content: '{"status":"completed","provider_result":"invented"}' }] }), []);
});
