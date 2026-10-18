import test from "node:test";
import assert from "node:assert/strict";
import { primaryResultFromOutputs, resultMetrics, supportingReceipts } from "../src/lib/resultPresentation.mjs";
import { campaignCopySections } from "../src/lib/campaignCopySections.mjs";

const main = { step_key: "main", operation: "google-docs.create-document", resolved_arguments: { title: "Campaign launch package", content: "The complete approved campaign copy." }, provider_result: { id: "transport-one", ret: { documentId: "doc-main", title: "Campaign launch package" } } };
const tracker = { step_key: "tracker", operation: "google-docs.create-document", resolved_arguments: { title: "Approval tracker", content: "The complete approval actions." }, provider_result: { id: "transport-two", ret: { documentId: "doc-tracker", title: "Approval tracker" } } };
const check = { step_key: "verify", operation: "google-docs.get-document", resolved_arguments: { documentId: "doc-tracker" }, provider_result: { id: "transport-read", ret: { documentId: "doc-tracker", title: "Approval tracker" } } };

test("a document verification finishes the run without replacing the main saved artifact", () => {
  const result = primaryResultFromOutputs([main, tracker, check], { title: "Campaign launch preparation" }, { primary_step_key: "verify" });
  assert.equal(result.kind, "document");
  assert.equal(result.preview.body, main.resolved_arguments.content);
  assert.equal(result.link, "https://docs.google.com/document/d/doc-main/edit");
  const unrelated = { ...check, provider_result: { ret: { documentId: "unrelated-doc" } } };
  assert.equal(primaryResultFromOutputs([main, unrelated], {}, { primary_step_key: "verify" }).kind, "result");
});
test("document totals count separate saved resources and deduplicate repeated receipts", () => {
  const activity = [main, main, tracker].map((output) => ({ status: "completed", output }));
  assert.deepEqual(resultMetrics([], activity), [{ value: "2", label: "documents created" }]);
  assert.deepEqual(resultMetrics([], [{ status: "failed", output: main }]), []);
});
test("supporting document links keep the tracker and omit duplicate primary readbacks", () => {
  const mainCheck = { ...check, step_key: "verify-main", provider_result: { ret: { documentId: "doc-main" } } };
  const receipts = supportingReceipts({}, [main, tracker, mainCheck].map((output) => ({ status: "completed", stepKey: output.step_key, tool: "Google Docs", action: "Saved document", output })),
    { link: "https://docs.google.com/document/d/doc-main/edit", provider: "Google Docs" }, { supporting_step_keys: ["main", "tracker", "verify-main"] });
  assert.equal(receipts.length, 1);
  assert.equal(receipts[0].title, "Approval tracker");
  assert.equal(receipts[0].link, "https://docs.google.com/document/d/doc-tracker/edit");
});
test("campaign tabs require every complete channel section and preserve its actual copy", () => {
  const headings = ["Google Search concept 1", "Google Search concept 2", ...[1,2,3].map((i) => `Platform-neutral social concept ${i}`), "Optional Business Profile post", ...[1,2,3].map((i) => `Indoor-screen copy concept ${i}`)];
  const body = headings.map((h) => `## ${h}\nComplete saved demonstration copy with a consistent consultation call to action.\n`).join("\n");
  assert.equal(campaignCopySections(body).flatMap((g) => g.sections).length, 9);
  assert.match(campaignCopySections(body)[0].sections[0].body, /Complete saved demonstration copy/);
  assert.equal(campaignCopySections(body.replace("## Google Search concept 1", "## Missing concept")), null);
});
