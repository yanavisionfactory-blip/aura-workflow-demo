import assert from "node:assert/strict";
import test from "node:test";

import {
  CATALOG,
  MARKETPLACE,
  catalogEntryFor,
  ensurePlanConnectionRoute,
  mergeMarketplaceApps,
  replaceToolCatalog,
  searchMarketplace,
} from "../src/lib/toolCatalog.js";

test("plan connections discover a newly certified exact Sheets route before authorizing", async () => {
  replaceToolCatalog({ marketplace: [
    { provider: "google", display_name: "Google Workspace", connectable: true, connection_backend: "native" },
  ] });
  assert.equal(catalogEntryFor("Google Sheets").routes.some((route) => route.provider === "google-sheets"), false);
  let discoveries = 0;
  const discover = async (name) => {
    discoveries += 1;
    assert.equal(name, "Google Sheets");
    return { apps: [{ provider: "google-sheets", display_name: "Google Sheets", connectable: true,
      connection_backend: "pipedream", connection_strategy: "oauth" }] };
  };
  const entry = await ensurePlanConnectionRoute("Google Sheets", "google-sheets", discover);
  assert.equal(entry.routes.find((route) => route.provider === "google-sheets")?.connectable, true);
  await ensurePlanConnectionRoute("Google Sheets", "google-sheets", discover);
  assert.equal(discoveries, 1);
});

test("discovery never upgrades an unverified route or substitutes shared Google consent", async () => {
  replaceToolCatalog({ marketplace: [
    { provider: "google", display_name: "Google Workspace", connectable: true, connection_backend: "native" },
  ] });
  const entry = await ensurePlanConnectionRoute("Google Sheets", "google-sheets", async () => ({
    apps: [{ provider: "google-sheets", display_name: "Google Sheets", connectable: false,
      availability: "coming_soon", connection_backend: "pipedream" }],
  }));
  assert.equal(entry.routes.find((route) => route.provider === "google")?.connectable, true);
  assert.equal(entry.routes.find((route) => route.provider === "google-sheets")?.connectable, false);
});

test("discovered providers are searchable but only released providers are selectable", () => {
  replaceToolCatalog({
    marketplace: [
      {
        provider: "linear",
        display_name: "Linear",
        categories: ["Project Management"],
        availability: "available",
        connectable: true,
        capability_count: 4,
        connection_strategy: "oauth",
        setup_hint: "Provider consent",
      },
      {
        provider: "make",
        display_name: "Make",
        categories: ["Automation"],
        availability: "verifying",
        connectable: false,
      },
    ],
  });

  assert.deepEqual(MARKETPLACE.map((tool) => tool.name), ["Linear", "Make"]);
  assert.deepEqual(CATALOG.map((tool) => tool.name), ["Linear"]);
  assert.equal(catalogEntryFor("linear")?.name, "Linear");
  assert.equal(catalogEntryFor("linear")?.connectionStrategy, "oauth");
  assert.match(catalogEntryFor("linear")?.desc, /Provider consent/);
  assert.equal(catalogEntryFor("make"), null);
  assert.equal(searchMarketplace("Linear")[0].name, "Linear");
  assert.deepEqual(
    searchMarketplace("Obscure Work App").map(({ name, requestable, availability }) => ({
      name,
      requestable,
      availability,
    })),
    [{ name: "Obscure Work App", requestable: true, availability: "requestable" }]
  );

  mergeMarketplaceApps([
    {
      provider: "salesforce",
      display_name: "Salesforce",
      categories: ["CRM"],
      availability: "available",
      connectable: true,
      connection_backend: "pipedream",
      connection_strategy: "secure_credentials",
      setup_hint: "Secure credentials required",
    },
    {
      provider: "legacy-key-app",
      display_name: "Legacy Key App",
      availability: "coming_soon",
      connectable: false,
    },
    {
      provider: "unsupported-app",
      display_name: "Unsupported App",
      availability: "requestable",
      connectable: false,
      requestable: true,
    },
  ]);

  assert.equal(catalogEntryFor("salesforce")?.connectionBackend, "pipedream");
  assert.equal(catalogEntryFor("salesforce")?.connectionStrategy, "secure_credentials");
  assert.equal(catalogEntryFor("salesforce")?.desc, "Secure credentials required");
  assert.equal(catalogEntryFor("legacy-key-app"), null);
  assert.equal(searchMarketplace("Legacy Key App")[0].availability, "coming_soon");
  assert.equal(searchMarketplace("Unsupported App")[0].requestable, true);
});

test("action and MCP routes appear as one app with both execution paths", () => {
  replaceToolCatalog({
    marketplace: [
      {
        provider: "notion",
        canonical_provider: "notion",
        display_name: "Notion",
        availability: "available",
        connectable: true,
        connection_backend: "pipedream",
        execution_backend: "pipedream_action",
      },
      {
        provider: "notion-mcp-v2",
        canonical_provider: "notion-mcp-v2",
        display_name: "Notion (MCP)",
        availability: "available",
        connectable: true,
        connection_backend: "pipedream",
        execution_backend: "pipedream_mcp",
      },
    ],
  });

  assert.deepEqual(MARKETPLACE.map((tool) => tool.name), ["Notion"]);
  assert.equal(CATALOG.length, 1);
  assert.equal(catalogEntryFor("notion-mcp-v2")?.name, "Notion");
  assert.deepEqual(
    catalogEntryFor("Notion")?.routes.map((route) => route.provider).sort(),
    ["notion", "notion-mcp-v2"],
  );
});

test("Meta search exposes the verified Pages route without satisfying Meta Ads", () => {
  replaceToolCatalog({ marketplace: [
    {
      provider: "facebook-pages",
      display_name: "Facebook Pages",
      aliases: ["Meta", "Meta Pages", "Meta Facebook", "Meta Facebook Pages"],
      availability: "available",
      connectable: true,
      connection_backend: "pipedream",
      connection_strategy: "oauth",
      setup_hint: "Provider consent",
      capability_count: 9,
    },
    {
      provider: "meta-ads",
      display_name: "Meta Ads",
      availability: "coming_soon",
      connectable: false,
    },
  ] });

  assert.deepEqual(searchMarketplace("Meta").map((tool) => tool.name), ["Facebook Pages", "Meta Ads"]);
  assert.equal(catalogEntryFor("Meta")?.provider, "facebook-pages");
  assert.equal(catalogEntryFor("Facebook Pages")?.connectionStrategy, "oauth");
  assert.equal(catalogEntryFor("Meta Ads"), null);
  assert.equal(searchMarketplace("Meta Ads")[0].connectable, false);
  assert.match(searchMarketplace("Meta Pages")[0].desc, /9 verified capabilities/);
});
