import assert from "node:assert/strict";
import test from "node:test";
import { applyPresentationCopy } from "../src/lib/canvaCopyEdit.mjs";
import { applyEmailCopy } from "../src/lib/emailCopyEdit.mjs";

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

test("AI edits preserve workflow data references in slides and email", () => {
  const original = { title: "Audience", subtitle: "", phases: [{ period: "Today", title: "News", items: ["Audience: {{steps.audiences.list[0].name}}"], scene: "lantern" }] };
  const revised = { title: "Audience", subtitle: "", slides: [{ period: "Today", title: "News", items: ["For {{steps.audiences.list[0].name}}"] }] };
  assert.equal(applyPresentationCopy(original, revised).phases[0].items[0], revised.slides[0].items[0]);
  assert.throws(() => applyPresentationCopy(original, { ...revised, slides: [{ ...revised.slides[0], items: ["For everyone"] }] }), /live information/);
  const email = { to: "me", subject: "News", body: "Hi {{steps.audiences.list[0].name}}", attachments: [{ filename: "design.pdf" }] };
  assert.deepEqual(applyEmailCopy(email, { subject: "Update", body: "Hello {{steps.audiences.list[0].name}}" }), { ...email, subject: "Update", body: "Hello {{steps.audiences.list[0].name}}" });
  assert.throws(() => applyEmailCopy(email, { subject: "Update", body: "Hello everyone" }), /live information/);
});
