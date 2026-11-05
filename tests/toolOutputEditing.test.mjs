import test from "node:test";
import assert from "node:assert/strict";
import { editableResultText, resultTextEditPrompt, validateResultTextEdit } from "../src/lib/toolOutputEditing.mjs";
import { toolResultEntries } from "../src/lib/toolResultViews.mjs";
import { primaryResultFromOutputs } from "../src/lib/resultPresentation.mjs";

const draft = { id: "draft", tool: "anthropic", status: "completed", output: {
  operation: "anthropic.chat", critic: { action: "accept" }, outcome_check: { status: "verified" },
  provider_result: { ret: { id: "original-receipt", content: [{ type: "text", text: "Original" }] } },
} };

test("draft and saved text revisions appear without replacing the provider receipt", () => {
  const original = structuredClone(draft);
  assert.equal(editableResultText(draft), "Original");
  const saved = { ...draft, output: { ...draft.output, user_revision: { text: "Approved edit" } } };
  assert.equal(saved.output.provider_result.ret.content[0].text, "Original");
  const [entry] = toolResultEntries([saved]);
  assert.equal(entry.preview.preview.body, "Approved edit");
  assert.equal(entry.userEdited, true);
  assert.equal(entry.response.ret.id, "original-receipt");
  assert.equal(entry.response.ret.content[0].text, "Original");
  assert.deepEqual(draft, original);
});

test("report revisions change only the generated body; external records cannot become editable text", () => {
  const report = { status: "completed", operation: "report.compose", output: {
    operation: "report.compose", critic: { action: "accept" }, outcome_check: { status: "verified" }, provider_result: {
    status: "draft", body: "Original report", title: "Report", sources: [{ id: "source-1" }], summary: "Saved summary",
  }, user_revision: { text: "Edited report" } } };
  assert.equal(editableResultText(report), "Original report");
  assert.equal(primaryResultFromOutputs([report.output]).preview.body, "Edited report");
  assert.equal(primaryResultFromOutputs([report.output]).userEdited, true);
  assert.equal(report.output.provider_result.body, "Original report");
  for (const step of [{ ...draft, status: "pending" }, { ...draft, output: { ...draft.output, operation: "sheets.read" } },
    { ...report, operation: "docs.get", output: { ...report.output, operation: "docs.get" } }]) {
    assert.equal(editableResultText(step), null);
  }
});

test("AI editing uses the current draft and rejects empty, oversized and malformed responses", () => {
  const prompt = resultTextEditPrompt("Manual change already applied", "Add conversions");
  assert.match(prompt, /Manual change already applied/);
  assert.match(prompt, /Add conversions/);
  assert.match(prompt, /untrusted content/);
  assert.throws(() => resultTextEditPrompt("x".repeat(50000), "Edit"), /too large/);
  assert.throws(() => resultTextEditPrompt("", "Edit"), /Enter/);
  for (const value of [null, {}, { text: "", summary: "Updated" }, { text: 3, summary: "Updated" },
    { text: "Valid", summary: null }, { text: "x".repeat(200001), summary: "Updated" }]) {
    assert.throws(() => validateResultTextEdit(value), /unchanged/);
  }
  assert.deepEqual(validateResultTextEdit({ text: "Edited", summary: "Shorter" }), { text: "Edited", summary: "Shorter" });
});
