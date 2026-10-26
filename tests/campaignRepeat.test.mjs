import test from "node:test";
import assert from "node:assert/strict";
import { campaignRepeatPrompt, savedRunActionLocation } from "../src/lib/runtimePlan.mjs";

const prefix = "AURA_CAMPAIGN_REPORT_V1\n";
const original = prefix + JSON.stringify({ attachment_name: "sample.xlsx" });
const fields = {
  client_name: "Sample", data_status: "anonymized_sample", currency: "USD",
  prior_start: "2026-08-24", prior_end: "2026-09-20",
  current_start: "2026-09-21", current_end: "2026-10-18",
  meta_attribution: "7-day click / 1-day view", ga4_attribution: "Data-driven",
  source_filename: "sample.xlsx", source_sha256: "a".repeat(64),
  google_ads: [{ period: "Prior" }, { period: "Current" }],
  meta_ads: [{ period: "Prior" }, { period: "Current" }],
  ga4: [{ period: "Prior" }, { period: "Current" }],
};
const step = (arguments_) => ({ operation: "sheets.campaign_report.create", arguments: arguments_ });

test("campaign repeat survives loss of the upload and uses current reviewed source rows", () => {
  const current = { ...fields, client_name: "Reviewed sample", spreadsheet_id: "old-receipt", plan_approved: true };
  const prompt = campaignRepeatPrompt(original, [step(current)]);
  const parsed = JSON.parse(prompt.slice(prefix.length));
  assert.equal(parsed.client_name, "Reviewed sample");
  assert.equal(parsed.source_sha256, fields.source_sha256);
  assert.deepEqual(parsed.ga4, fields.ga4);
  assert.equal(parsed.attachment_name, undefined);
  assert.equal(parsed.spreadsheet_id, undefined);
  assert.equal(parsed.plan_approved, undefined);
  assert.equal(savedRunActionLocation(prompt).state.workflowPrompt, prompt);
});

test("repeat is limited to one campaign recipe with complete, bounded saved inputs", () => {
  assert.equal(campaignRepeatPrompt("Ordinary task", [step(fields)]), null);
  assert.equal(campaignRepeatPrompt(original, [step(fields), step(fields)]), null);
  assert.equal(campaignRepeatPrompt(original, [{ ...step(fields), operation: "sheets.update" }]), null);
  assert.equal(campaignRepeatPrompt(original, [step({ ...fields, source_sha256: "missing" })]), null);
  assert.equal(campaignRepeatPrompt(original, [step({ ...fields, ga4: [] })]), null);
  assert.equal(campaignRepeatPrompt(original, [step({ ...fields, client_name: undefined })]), null);
  assert.equal(campaignRepeatPrompt(original, [step({ ...fields, client_name: "x".repeat(20000) })]), null);
  assert.equal(campaignRepeatPrompt(original, undefined), null);
});
