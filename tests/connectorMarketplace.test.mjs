import assert from "node:assert/strict";
import test from "node:test";

import {
  CATALOG,
  MARKETPLACE,
  catalogEntryFor,
  mergeMarketplaceApps,
  replaceToolCatalog,
  searchMarketplace,
} from "../src/lib/toolCatalog.js";

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
