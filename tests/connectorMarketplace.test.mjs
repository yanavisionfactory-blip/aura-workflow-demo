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
    },
    {
      provider: "legacy-key-app",
      display_name: "Legacy Key App",
      availability: "coming_soon",
      connectable: false,
    },
  ]);

  assert.equal(catalogEntryFor("salesforce")?.connectionBackend, "pipedream");
  assert.equal(catalogEntryFor("legacy-key-app"), null);
  assert.equal(searchMarketplace("Legacy Key App")[0].availability, "coming_soon");
});
