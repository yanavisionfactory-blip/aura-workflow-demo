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

for (const [provider, name] of [["gmail", "Gmail"], ["google-drive", "Google Drive"]]) {
  test(`${name} prefers certified public consent while keeping the existing Google route`, () => {
    for (const reverse of [false, true]) {
      const marketplace = [
        { provider: "google", display_name: "Google Workspace", connectable: true,
          connection_backend: "nango", connection_strategy: "oauth", source: "native" },
        { provider, display_name: name, connectable: true, preferred_connection: true,
          connection_backend: "pipedream", connection_strategy: "oauth" },
      ];
      replaceToolCatalog({ marketplace: reverse ? marketplace.reverse() : marketplace });
      const entry = catalogEntryFor(name);
      assert.equal(entry.provider, provider);
      assert.equal(entry.connectionBackend, "pipedream");
      assert.equal(entry.preferredConnection, true);
      assert.equal(searchMarketplace(name).filter(item => item.name === name).length, 1);
      assert.equal(entry.routes.find(route => route.provider === "google").connectionBackend, "nango");
    }
  });

  test(`${name} does not treat an uncertified public route as an authorized connection`, async () => {
    replaceToolCatalog({ marketplace: [
      { provider: "google", display_name: "Google Workspace", connectable: true,
        connection_backend: "nango", connection_strategy: "oauth", source: "native" },
    ] });
    const entry = await ensurePlanConnectionRoute(name, provider, async () => ({ apps: [
      { provider, display_name: name, connectable: false, preferred_connection: true,
        availability: "verifying", connection_backend: "pipedream", connection_strategy: "oauth" },
    ] }));
    assert.equal(entry.provider, "google");
    assert.equal(entry.routes.find(route => route.provider === provider).connectable, false);
  });
}

test("OpenAI connection explains API access and preserves ChatGPT search aliases", () => {
  replaceToolCatalog({ marketplace: [
    { provider: "openai", display_name: "OpenAI (ChatGPT)", connectable: true,
      connection_backend: "pipedream", connection_strategy: "secure_credentials",
      setup_hint: "Secure credentials required", capability_count: 46 },
  ] });
  for (const query of ["OpenAI", "OpenAI API", "ChatGPT", "OpenAI (ChatGPT)"]) {
    const entry = catalogEntryFor(query);
    assert.equal(entry.provider, "openai");
    assert.equal(entry.name, "OpenAI API");
    assert.equal(entry.connectionStrategy, "secure_credentials");
    assert.match(entry.desc, /API key/);
    assert.match(entry.desc, /conversation history are not connected/);
    assert.equal(searchMarketplace(query)[0].provider, "openai");
  }
  mergeMarketplaceApps([{ provider: "openai", display_name: "OpenAI (ChatGPT)",
    connectable: true, connection_backend: "pipedream", connection_strategy: "secure_credentials" }]);
  assert.equal(searchMarketplace("OpenAI").length, 1);
});

test("exact Google Sheets identity wins over another connector's search aliases", () => {
  replaceToolCatalog({ marketplace: [
    { provider: "meta-ads-mcp", display_name: "A shared ads connector", connectable: true,
      aliases: ["Google Sheets", "google-sheets"], connection_backend: "managed_mcp" },
    { provider: "google-sheets", display_name: "Google Sheets", connectable: true,
      connection_backend: "pipedream" },
  ] });
  assert.equal(catalogEntryFor("Google Sheets").provider, "google-sheets");
  assert.equal(catalogEntryFor("google-sheets").provider, "google-sheets");
});

test("an ambiguous alias never silently selects the first unrelated connector", () => {
  replaceToolCatalog({ marketplace: [
    { provider: "first", display_name: "First", connectable: true, aliases: ["Shared app"] },
    { provider: "second", display_name: "Second", connectable: true, aliases: ["Shared app"] },
  ] });
  assert.equal(catalogEntryFor("Shared app"), null);
  assert.equal(catalogEntryFor(""), null);
  assert.equal(catalogEntryFor("second").provider, "second");
});

test("managed social connections share app cards and preserve existing authorization routes", () => {
  replaceToolCatalog({ marketplace: [
    { provider: "x", display_name: "X (Twitter)", connectable: true, connection_backend: "native", preferred_connection: true },
    { provider: "x-zernio", display_name: "X (Twitter)", canonical_provider: "x", connectable: true, connection_backend: "zernio", preferred_connection: true },
    { provider: "tiktok", display_name: "TikTok", connectable: true, connection_backend: "native", preferred_connection: true },
    { provider: "tiktok-zernio", display_name: "TikTok", canonical_provider: "tiktok", connectable: true, connection_backend: "zernio", preferred_connection: true },
    { provider: "tiktok-ads-manager", display_name: "TikTok Ads", connectable: true, connection_backend: "pipedream" },
  ] });
  assert.equal(searchMarketplace("X").length, 1);
  assert.equal(catalogEntryFor("X").provider, "x-zernio");
  assert.equal(catalogEntryFor("TikTok").provider, "tiktok-zernio");
  assert.equal(catalogEntryFor("TikTok Ads").provider, "tiktok-ads-manager");
  assert.deepEqual(catalogEntryFor("X").routes.map(route => route.provider).sort(), ["x", "x-zernio"]);
});

test("social apps stay visible in a large catalog without bypassing readiness", () => {
  replaceToolCatalog({ marketplace: [
    ...Array.from({ length: 150 }, (_, index) => ({ provider: `app-${index}`, display_name: `App ${index}`, connectable: true })),
    { provider: "tiktok", display_name: "TikTok", connectable: true, connection_backend: "native", preferred_connection: true },
    { provider: "tiktok-ads", display_name: "TikTok Ads", connectable: false },
    { provider: "tiktok-ads-manager", display_name: "TikTok Ads Manager", connectable: true, connection_backend: "pipedream" },
    { provider: "x", display_name: "X (Twitter)", connectable: false, connection_backend: null },
    { provider: "twitter-v2", display_name: "Twitter (v2)", connectable: false },
    { provider: "xero", display_name: "Xero", connectable: true },
  ] });
  assert.deepEqual(searchMarketplace("").slice(0, 3).map(item => item.name), ["TikTok", "TikTok Ads", "X (Twitter)"]);
  assert.equal(searchMarketplace("X").length, 1);
  assert.equal(searchMarketplace("X")[0].connectable, false);
  assert.equal(catalogEntryFor("X"), null);
  assert.equal(searchMarketplace("Twitter")[0].name, "X (Twitter)");
  assert.equal(searchMarketplace("TikTok Ads").length, 1);
  assert.equal(catalogEntryFor("TikTok Ads Manager").provider, "tiktok-ads-manager");
  assert.equal(catalogEntryFor("TikTok").provider, "tiktok");
  assert.equal(catalogEntryFor("TikTok Ads").routes.find(route => route.provider === "tiktok-ads").connectable, false);
});

test("configured X uses the registered native route and retains legacy route IDs", () => {
  replaceToolCatalog({ marketplace: [
    { provider: "twitter-v2", display_name: "Twitter (v2)", connectable: true, connection_backend: "nango" },
    { provider: "x", display_name: "X (Twitter)", connectable: true, connection_backend: "native", preferred_connection: true },
  ] });
  assert.equal(catalogEntryFor("Twitter").provider, "x");
  assert.equal(catalogEntryFor("X").provider, "x");
  assert.deepEqual(catalogEntryFor("X").routes.map(route => route.provider).sort(), ["twitter-v2", "x"]);
});

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

test("managed Sheets consent wins over broad Google consent and keeps the legacy plan route", () => {
  replaceToolCatalog({ marketplace: [
    { provider: "google", display_name: "Google Workspace", connectable: true,
      connection_backend: "nango", connection_strategy: "oauth", source: "native" },
    { provider: "google-sheets", display_name: "Google Sheets", connectable: true,
      connection_backend: "pipedream", connection_strategy: "oauth", preferred_connection: true },
  ] });
  const sheets = catalogEntryFor("Google Sheets");
  assert.equal(sheets.provider, "google-sheets");
  assert.equal(sheets.connectionBackend, "pipedream");
  assert.equal(sheets.routes.find(route => route.provider === "google").connectionBackend, "nango");
  assert.equal(catalogEntryFor("Google Docs").connectionBackend, "nango");
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

test("new Docs customers get managed consent while existing Workspace routes remain available", () => {
  for (const broadFirst of [false, true]) {
    const entries = [
      { provider: "google", display_name: "Google Workspace", connectable: true,
        connection_backend: "nango", connection_strategy: "oauth", source: "native" },
      { provider: "google-docs", display_name: "Google Docs", connectable: true,
        connection_backend: "pipedream", connection_strategy: "oauth", preferred_connection: true },
    ];
    replaceToolCatalog({ marketplace: broadFirst ? entries : entries.toReversed() });
    const docs = catalogEntryFor("Google Docs");
    assert.equal(docs.provider, "google-docs");
    assert.equal(docs.connectionBackend, "pipedream");
    assert.equal(docs.preferredConnection, true);
    assert.equal(docs.routes.find(route => route.provider === "google").connectionBackend, "nango");
    assert.equal(catalogEntryFor("Google Drive").provider, "google");
    assert.equal(catalogEntryFor("Google Calendar").provider, "google");
  }
});

