import test from "node:test";
import assert from "node:assert/strict";
import { adsInputResult } from "../src/lib/adsInputResult.mjs";
import { savedToolResponse } from "../src/lib/savedToolResponse.mjs";

const report = (id, client = "client-1", cost = "12000000") => ({
  id, tool: "Google Ads", action: "Read campaigns", operation: "google-ads.create-campaign-report",
  status: "completed", hasResponse: true, inputs: { accountId: "manager", customerClientId: client, segments: [] },
  response: { ret: { query: "SELECT campaign.name, metrics.cost_micros FROM campaign", results: [
    { campaign: { id: "campaign-1", name: "Search", status: "ENABLED" }, metrics: { costMicros: cost, clicks: "0", impressions: "100" } },
  ] } },
});
const metadata = (id, currency) => ({ id: `metadata-${id}-${currency}`, tool: "Google Ads", status: "completed", hasResponse: true,
  response: { ret: [{ customer: { id, currencyCode: currency, timeZone: "Europe/Berlin" } }] } });
const fact = (item, label) => item.facts.find((f) => f.label === label)?.value;

test("input screens show the reporting client, not the login manager, and match its metadata", () => {
  const result = adsInputResult([report("read"), metadata("manager", "USD"), metadata("client-1", "EUR")]);
  assert.equal(result.datasets.length, 1);
  assert.equal(fact(result.datasets[0], "Account"), "client-1");
  assert.equal(fact(result.datasets[0], "Currency"), "EUR");
  assert.match(fact(result.datasets[0], "Reporting scope"), /No reporting-date filter/);
  assert.equal(result.datasets[0].campaigns[0].metrics.find((m) => m.label === "Spend").value, "12");
});
test("overlapping reports remain separate and conflicting currency metadata is not guessed", () => {
  const result = adsInputResult([report("read-1"), report("read-2"), metadata("client-1", "EUR"), metadata("client-1", "USD")]);
  assert.equal(result.datasets.length, 2);
  assert.equal(fact(result.datasets[0], "Currency"), undefined);
  assert.equal(result.datasets[0].campaigns.length, 1);
});
test("failed and pending source calls never produce an input result screen", () => {
  assert.equal(adsInputResult([{ ...report("failed"), status: "failed" }, { ...report("pending"), status: "pending" }]).datasets.length, 0);
});
test("empty Meta reports preserve each account and period without zero metrics", () => {
  const entries = ["2025", "2026"].map((year) => ({ id: year, tool: "Meta Ads", status: "completed", hasResponse: true,
    response: { data: [], account_id: "act-test", account: { currency: "EUR" }, date_range: { since: `${year}-01-01`, until: `${year}-06-30` } } }));
  const result = adsInputResult(entries);
  assert.deepEqual(result.accounts, ["act-test"]);
  assert.equal(result.datasets.length, 2);
  assert.ok(result.datasets.every((item) => item.empty && !item.campaigns.length));
  assert.match(fact(result.datasets[1], "Reporting dates"), /2026-01-01/);
});
test("malformed metric values remain unavailable while real zero remains zero", () => {
  for (const cost of [false, [], {}, "   ", null]) {
    const result = savedToolResponse(report("read", "client-1", cost));
    assert.equal(result.campaigns[0].metrics.find((m) => m.label === "Spend").value, "Unavailable");
    assert.equal(result.campaigns[0].metrics.find((m) => m.label === "Clicks").value, "0");
    assert.equal(result.campaigns[0].metrics.find((m) => m.label === "CPC").value, "Unavailable");
  }
});
