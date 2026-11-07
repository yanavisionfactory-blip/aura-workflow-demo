import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { reconcileToolOmissions } from "../src/lib/toolOmissions.mjs";
import { promptToolHints } from "../src/lib/promptToolHints.mjs";

const cases = JSON.parse(readFileSync(new URL("./fixtures/tool-omissions.json", import.meta.url)));
for (const item of cases) {
  test(item.name, () => {
    const result = reconcileToolOmissions(item.prompt, item.selected, item.excluded);
    assert.deepEqual(result.selectedTools, item.expected);
    assert.deepEqual(result.excludedFamilies, item.families);
    assert.deepEqual(reconcileToolOmissions(item.prompt, result.selectedTools, result.excludedFamilies), result);
  });
}

test("copied omission does not suggest reconnecting either Reddit product", () => {
  const apps = ["Meta Ads", "Google Ads", "Reddit Ads", "Reddit", "Google Sheets", "Canva"]
    .map((name) => ({ name, provider: name.toLowerCase().replaceAll(" ", "-") }));
  assert.deepEqual(new Set(promptToolHints(cases[0].prompt, apps)), new Set(cases[0].expected));
});
