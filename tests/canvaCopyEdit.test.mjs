import assert from "node:assert/strict";
import test from "node:test";
import { applyPresentationCopy } from "../src/lib/canvaCopyEdit.mjs";

test("AURA slide revisions preserve illustrations, slide count, and action arguments", () => {
  const original = { layout: "slides", title: "Draft", subtitle: "Old", phases: [{ period: "1", title: "Before", items: ["One"], scene: "lantern" }], export: "pdf" };
  const next = applyPresentationCopy(original, { title: "New", subtitle: "Fresh", slides: [{ period: "Today", title: "After", items: ["Two"] }] });
  assert.deepEqual(next, { ...original, title: "New", subtitle: "Fresh", phases: [{ ...original.phases[0], period: "Today", title: "After", items: ["Two"] }] });
  assert.equal(original.title, "Draft");
});

test("AURA cannot silently add slides or change the approved action", () => {
  assert.throws(() => applyPresentationCopy({ phases: [{}] }, { title: "X", subtitle: "", slides: [] }), /could not apply/);
  assert.throws(() => applyPresentationCopy({ phases: [{}] }, { title: "X", subtitle: "", slides: [{ period: "", title: "", items: [4] }] }), /could not apply/);
});
