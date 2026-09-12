import assert from "node:assert/strict";
import test from "node:test";

import {
  CATALOG,
  MARKETPLACE,
  catalogEntryFor,
  replaceToolCatalog,
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
});
