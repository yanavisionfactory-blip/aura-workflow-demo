import test from "node:test";
import assert from "node:assert/strict";
import { parseCampaignDelivery } from "../src/lib/campaignDelivery.mjs";

const bundle = () => ({ kind: "campaign_launch", schemaVersion: 2, demo: true, title: "Launch review", client: "Fictional demo", summary: "Prepared", brief: { goal: "Demonstrate draft review" }, publicationStatus: "unpublished", channels: [{ name: "Search", drafts: [{ id: "copy1", title: "Draft", fields: [{ label: "Headline", text: "Complete saved draft text" }] }] }], approvals: [{ item: "Budget", status: "Needs input" }], assets: [], manualSteps: ["Confirm the landing page"], consistency: ["No invented offer"], links: [], questions: [], execution: {} });
test("campaign results preserve full draft copy and do not import execution instructions", () => {
  const parsed = parseCampaignDelivery({ ...bundle(), tools: ["publish"], execution_options: { publish: true } });
  assert.equal(parsed.channels[0].drafts[0].fields[0].text, "Complete saved draft text");
  assert.equal(parsed.tools, undefined);
  assert.equal(parsed.execution_options, undefined);
});
test("a campaign results import cannot publish or approve a campaign", () => {
  assert.throws(() => parseCampaignDelivery({ ...bundle(), publicationStatus: "published" }), /unpublished/);
  assert.throws(() => parseCampaignDelivery({ ...bundle(), approvals: [{ item: "Budget", status: "Approved" }] }), /cannot grant approval/);
});
test("campaign results reject incomplete bodies, unsafe output links and malformed brief values", () => {
  assert.throws(() => parseCampaignDelivery({ ...bundle(), channels: [{ name: "Search", drafts: [{ title: "Draft", fields: [] }] }] }), /complete/);
  assert.throws(() => parseCampaignDelivery({ ...bundle(), links: [{ label: "Output", url: "https://example.com/?access_token=secret" }] }), /safe/);
  assert.throws(() => parseCampaignDelivery({ ...bundle(), brief: { goal: "Demo", budget: { unknown: true } } }), /readable/);
});
