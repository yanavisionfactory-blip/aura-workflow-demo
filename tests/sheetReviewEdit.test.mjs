import test from "node:test";
import assert from "node:assert/strict";
import { applySheetEdits, sheetComparisonMarkdown } from "../src/lib/sheetReviewEdit.mjs";

const draft = { spreadsheet_id: "approved-book", range: "'Comparison'!A1:C1000", values: [["A", "$70", "One"], ["B", "$44.50", "Two"]] };

test("AURA edits only addressed cells and preserves destination, row order and other values", () => {
  const before = structuredClone(draft);
  const next = applySheetEdits(draft, { summary: "Clarified the assessment", changes: [{ row: 1, column: 2, value: "Analytical assessment: Two" }], spreadsheet_id: "other", range: "Z100" });
  assert.deepEqual(next, { ...draft, values: [["A", "$70", "One"], ["B", "$44.50", "Analytical assessment: Two"]] });
  assert.deepEqual(draft, before);
});

test("invalid and partial model edits never alter the draft", () => {
  for (const change of [{ row: -1, column: 1, value: "x" }, { row: 2, column: 1, value: "x" },
    { row: 1, column: 3, value: "x" }, { row: 1.5, column: 1, value: "x" },
    { row: 1, column: 1, value: { text: "x" } }, { row: 1, column: 1, value: Infinity },
    { row: 1, column: 1, value: '=IMPORTXML("https://example.invalid", "//x")' }]) {
    const before = structuredClone(draft);
    assert.throws(() => applySheetEdits(draft, { summary: "Edit", changes: [{ row: 0, column: 2, value: "First" }, change] }));
    assert.deepEqual(draft, before);
  }
  assert.throws(() => applySheetEdits(draft, { values: [["replacement"]] }));
  assert.throws(() => applySheetEdits(draft, { summary: "Duplicate", changes: [1, 2].map(() => ({ row: 0, column: 0, value: "x" })) }));
});

test("reviewed Markdown keeps table columns intact for product-name pipes and multiline cells", () => {
  const md = sheetComparisonMarkdown(["Brand", "Terms"], [["A | B", "1 oz\n$70"], ["<script>", "Unavailable"]]);
  assert.equal(md, "| Brand | Terms |\n| --- | --- |\n| A \\| B | 1 oz $70 |\n| &lt;script&gt; | Unavailable |");
});
