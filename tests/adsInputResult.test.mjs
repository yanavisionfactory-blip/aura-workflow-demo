import test from "node:test";
import assert from "node:assert/strict";
import { adsInputResult, metaEmptyResultHelp } from "../src/lib/adsInputResult.mjs";
import { savedToolResponse } from "../src/lib/savedToolResponse.mjs";
import { toolResultEntries } from "../src/lib/toolResultViews.mjs";

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

test("empty Meta recovery points to the checked account and dates without claiming a permission cause", () => {
  const entry = { id: "empty-meta", tool: "Meta Ads", status: "completed", hasResponse: true,
    operation: "meta-ads.insights.get", response: { data: [], account: { id: "act_123", name: "Client account" },
      date_range: { since: "2026-10-01", until: "2026-10-31" }, level: "account" } };
  const dataset = adsInputResult([entry]).datasets[0];
  const help = metaEmptyResultHelp(dataset);
  assert.equal(help.adsManagerUrl, "https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=123");
  assert.equal(help.accountName, "Client account");
  assert.equal(help.dates, "2026-10-01 – 2026-10-31");
  assert.equal(help.level, "account");
  assert.match(help.steps.join(" "), /If the account differs/);
  assert.doesNotMatch(help.steps.join(" "), /business_management|grant more permissions|zero performance/);
  assert.equal(metaEmptyResultHelp({ ...dataset, empty: false }), null);
  assert.equal(metaEmptyResultHelp(adsInputResult([report("google")]).datasets[0]), null);
});

test("recovery never constructs an Ads Manager link from unvalidated IDs", () => {
  for (const account of ["123&token=secret", "javascript:alert(1)", "portfolio-name", undefined]) {
    const dataset = { entry: { tool: "Meta Ads" }, empty: true, facts: [{ label: "Account", value: account }] };
    assert.equal(metaEmptyResultHelp(dataset).adsManagerUrl, null);
  }
});

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

test("account discovery does not hide an empty campaign result and exposes access coverage", () => {
  const discovery = { accounts: [{ id: "act_123", name: "Named account", currency: "EUR" }],
    coverage: { status: "partial", warnings: ["Business access is unavailable"] } };
  const common = { tool: "Meta Ads", status: "completed", hasResponse: true };
  const result = adsInputResult([
    { ...common, id: "accounts", operation: "meta-ads.accounts.list", response: { data: discovery.accounts, account_discovery: discovery } },
    { ...common, id: "campaigns", operation: "meta-ads.campaigns.list", response: { data: [], account_id: "act_123" } },
  ]);
  assert.equal(result.datasets.length, 1);
  assert.equal(result.datasets[0].empty, true);
  assert.deepEqual(result.discovery, discovery);
  assert.match(fact(result.summaries[0], "Discovered accounts"), /Named account · act_123/);
  assert.match(fact(result.summaries[0], "Access limitations"), /Business access/);
});

test("Reddit campaign results retain purchase definitions, reporting dates and missing values", () => {
  const result = savedToolResponse({ tool: "Reddit Ads", response: { data: [{ campaign_id: "c1", campaign_name: "Ended campaign",
    spend: 12, impressions: 100, clicks: 4, purchase_conversions: null, purchase_conversion_value: null }],
    account_id: "a2_123", account: { currency: "EUR", time_zone_id: "Europe/Amsterdam" },
    date_range: { starts_at: "2024-11-08T00:00:00Z", ends_at: "2026-11-08T10:00:00Z" } } });
  assert.equal(result.campaigns.length, 1);
  assert.equal(result.campaigns[0].metrics.find((m) => m.label === "Conversions").value, "Unavailable");
  assert.equal(result.campaigns[0].metrics.find((m) => m.label === "CPC").value, "3");
  assert.equal(fact(result, "Timezone"), "Europe/Amsterdam");
  assert.match(fact(result, "Reporting dates"), /2024-11-08/);
  assert.match(result.note, /Reddit-attributed purchases/);
});

test("Pipeboard receipts render under Meta Ads and retain archived campaigns without invented metrics", () => {
  const entries = toolResultEntries([{ id: "pipeboard-campaigns", tool: "agent-meta-ads-dda02350f7", status: "completed",
    operation: "get_campaigns", output: { operation: "get_campaigns", resolved_arguments: { account_id: "act_123" },
      provider_result: { is_error: false, structured_content: { result: JSON.stringify({ data: [
        { id: "1", account_id: "123", name: "Archived campaign", status: "ARCHIVED" },
      ] }) } } } }]);
  assert.equal(entries[0].tool, "Meta Ads");
  const result = adsInputResult(entries);
  assert.equal(result.datasets[0].campaigns[0].title, "Archived campaign");
  assert.equal(result.datasets[0].campaigns[0].status, "ARCHIVED");
  assert.ok(result.datasets[0].campaigns[0].metrics.every((metric) => metric.value === "Unavailable"));
});

test("Pipeboard metadata enriches empty insights without being mistaken for campaign data", () => {
  const common = { tool: "Meta Ads", status: "completed", hasResponse: true };
  const receipt = (value) => ({ is_error: false, structured_content: { result: JSON.stringify(value) } });
  const result = adsInputResult([
    { ...common, id: "info", operation: "get_account_info", response: receipt({ id: "act_123", account_id: "123", name: "Verified account", currency: "EUR" }) },
    { ...common, id: "insights", operation: "get_insights", inputs: { object_id: "act_123", time_range: "maximum" }, response: receipt({ data: [] }) },
  ]);
  assert.equal(result.datasets.length, 1);
  assert.equal(result.datasets[0].empty, true);
  assert.equal(fact(result.datasets[0], "Currency"), "EUR");
  assert.match(fact(result.datasets[0], "Reporting scope"), /Maximum history/);
});

test("inventory scope, statuses and permission gaps remain explicit", () => {
  const result = savedToolResponse({ tool: "Meta Ads", operation: "meta-ads.campaigns.list", response: {
    data: [], inventory_scope: { date_filter: "none", effective_status: ["ACTIVE", "ARCHIVED", "DELETED"] },
    account_discovery: { accounts: [], permissions: { ads_read: "granted", business_management: "not_granted" }, coverage: { status: "partial" } },
  } });
  assert.match(fact(result, "Reporting scope"), /no date filter/);
  assert.match(fact(result, "Status coverage"), /ARCHIVED, DELETED/);
  assert.equal(fact(result, "Business discovery permission"), "not_granted");
});

test("malformed or error-marked Pipeboard envelopes never invent empty reporting results", () => {
  for (const response of [
    { is_error: true, structured_content: { result: '{"data":[]}' } },
    { is_error: false, structured_content: { result: 'not-json' } },
  ]) assert.equal(savedToolResponse({ tool: "Meta Ads", operation: "get_insights", response }).empty, false);
});

test("empty inventory exposes unsupported deleted coverage without claiming it was checked", () => {
  const result = adsInputResult([{ id: "limited-inventory", tool: "Meta Ads", status: "completed", hasResponse: true,
    operation: "meta-ads.campaigns.list", response: { data: [], inventory_scope: {
      date_filter: "none", effective_status: ["ACTIVE", "PAUSED", "ARCHIVED"], coverage: "partial",
      unavailable_effective_status: ["DELETED"], limitation: "Deleted inventory is unavailable from this endpoint.",
    } } }]);
  assert.equal(result.datasets[0].empty, true);
  assert.doesNotMatch(fact(result.datasets[0], "Status coverage"), /DELETED/);
  assert.equal(fact(result.datasets[0], "Unavailable statuses"), "DELETED");
  assert.match(fact(result.datasets[0], "Inventory limitation"), /unavailable/);
});

