import test from "node:test";
import assert from "node:assert/strict";
import { replaceToolCatalog } from "../src/lib/toolCatalog.js";
import { buildPlanConnectionTools } from "../src/lib/planConnections.mjs";

const requirement = (provider, permissions) => ({ provider_hint: provider, capability: provider,
  status: "pending", required_permissions: permissions, reason: `Authorize exact operations for ${provider}` });

test("report connections follow executable providers, never another app's search aliases", () => {
  replaceToolCatalog({ marketplace: [
    { provider: "tiktok-zernio", display_name: "TikTok", connectable: true,
      aliases: ["google-sheets", "Google Sheets", "meta-ads", "Meta Ads"] },
    { provider: "google-sheets", display_name: "Google Sheets", connectable: false },
    { provider: "meta-ads", display_name: "Meta Ads", connectable: false },
  ] });
  const tools = buildPlanConnectionTools([], { connectionChecklist: [
    requirement("google-sheets", ["google-sheets.new-spreadsheet"]),
    requirement("meta-ads", ["meta-ads.insights.read"]),
  ] });
  assert.deepEqual(tools.map(({ name, provider }) => ({ name, provider })), [
    { name: "Google Sheets", provider: "google-sheets" },
    { name: "Meta Ads", provider: "meta-ads" },
  ]);
});

test("saved report steps use their exact route and built-in reports require no external account", () => {
  replaceToolCatalog({ marketplace: [
    { provider: "google-sheets", display_name: "Google Sheets", connectable: true },
    { provider: "tiktok-zernio", display_name: "TikTok", connectable: true },
    { provider: "openai", display_name: "ChatGPT", connectable: true },
  ] });
  const steps = [
    { tool: "TikTok", toolSlug: "google-sheets", operation: "google-sheets.new-spreadsheet",
      flow: [{ label: "Uses", value: "TikTok" }] },
    { tool: "ChatGPT", toolSlug: "aura", operation: "report.compose" },
  ];
  const original = JSON.stringify(steps);
  const tools = buildPlanConnectionTools(steps, { connectionChecklist: [
    requirement("google-sheets", ["google-sheets.new-spreadsheet", "google-sheets.get-spreadsheet"]),
  ] });
  assert.equal(tools.length, 1);
  assert.equal(tools[0].name, "Google Sheets");
  assert.equal(tools[0].provider, "google-sheets");
  assert.deepEqual(tools[0].requiredPermissions, ["google-sheets.new-spreadsheet", "google-sheets.get-spreadsheet"]);
  assert.equal(JSON.stringify(steps), original);
});

test("an uncatalogued custom route is gated only by a saved backend requirement", () => {
  const step = { tool: "Private analysis", toolSlug: "agent-private-analysis", operation: "analysis.read" };
  assert.deepEqual(buildPlanConnectionTools([step]), []);
  const tools = buildPlanConnectionTools([step], { connectionChecklist: [
    requirement("agent-private-analysis", ["analysis.read"]),
  ] });
  assert.equal(tools.length, 1);
  assert.equal(tools[0].provider, "agent-private-analysis");
});
