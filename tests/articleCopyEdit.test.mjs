import test from "node:test";
import assert from "node:assert/strict";
import { applyArticleCopy } from "../src/lib/articleCopyEdit.mjs";

test("article improvements only revise wording and preserve the draft destination and metadata", () => {
  const original = { post: 107, status: "draft", title: "Demo guide", content: "<p>Original homeowner advice.</p>", excerpt: "Original excerpt", categories: [3] };
  const next = applyArticleCopy(original, { title: "Clear demo guide", content: "<p>Clear homeowner advice.</p>", post: 999, status: "publish", categories: [] });
  assert.deepEqual(next, { ...original, title: "Clear demo guide", content: "<p>Clear homeowner advice.</p>" });
  assert.equal(original.title, "Demo guide");
});

test("article revisions preserve live references and reject truncated or active content", () => {
  const original = { title: "Guide for {{steps.intake.city}}", content: `<p>${"Useful homeowner advice. ".repeat(120)} {{steps.intake.business}}</p>` };
  assert.throws(() => applyArticleCopy(original, { title: "Guide", content: original.content }), /live information/);
  assert.throws(() => applyArticleCopy(original, { title: original.title, content: "<p>{{steps.intake.business}} Short summary.</p>" }), /incomplete/);
  assert.throws(() => applyArticleCopy(original, { title: original.title, content: original.content + '<script>alert(1)</script>' }), /formatting/);
  assert.throws(() => applyArticleCopy(original, { title: original.title, content: original.content + '<a href="javascript:alert(1)">Click</a>' }), /formatting/);
  assert.throws(() => applyArticleCopy(original, { title: "", content: "" }), /revision/);
});
