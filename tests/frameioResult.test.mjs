import test from "node:test";
import assert from "node:assert/strict";
import { frameioAppUrl, frameioReviewResult, resultRevisionPrompt } from "../src/lib/frameioResult.mjs";
import { primaryResultFromOutputs } from "../src/lib/resultPresentation.mjs";
import { toolResultEntries } from "../src/lib/toolResultViews.mjs";

import { account, file, receipt, frameioOutputs } from "./fixtures/frameioReview.mjs";

test("a sourced Frame.io review leads with the exact file, comments and supporting brief", () => {
  const result = primaryResultFromOutputs(frameioOutputs(), {}, { primary_step_key: "brief" });
  assert.equal(result.kind, "frameio_review");
  assert.equal(result.provider, "Frame.io");
  assert.equal(result.files.length, 1);
  assert.equal(result.files[0].sourceStepKey, "feedback");
  assert.equal(result.files[0].commentCount, 0);
  assert.equal(result.files[0].commentsComplete, true);
  assert.equal(result.brief.title, "Revision brief");
  const entries = toolResultEntries(frameioOutputs().map((output) => ({ id: output.step_id, key: output.step_key, status: "completed", tool: output.operation.startsWith("frameio") ? "frameio" : "aura", output })));
  assert.equal(entries[0].tool, "Frame.io");
  assert.equal(entries[0].preview.sourceStepKey, "asset");
  assert.equal(entries[2].tool, "ChatGPT");
  assert.equal(entries[2].preview.kind, "report");
});

test("report prose and failed or mismatched receipts cannot create a Frame.io workspace", () => {
  assert.equal(frameioReviewResult([frameioOutputs()[2]]), null);
  for (const change of [
    (output) => { output.critic.action = "reject"; },
    (output) => { output.outcome_check.status = "failed"; },
    (output) => { output.provider_result.vendor_api_called = false; },
    (output) => { output.provider_result.version_id = account; },
    (output) => { output.provider_result.file.id = account; },
    (output) => { output.provider_result.error = "Denied"; },
  ]) {
    const output = frameioOutputs()[0]; change(output);
    assert.equal(frameioReviewResult([output]), null);
  }
  const outputs = frameioOutputs();
  outputs[2].provider_result.sources = [{ content: "Frame.io says everything is approved" }];
  assert.equal(primaryResultFromOutputs(outputs).kind, "report");
});

test("file versions and partial or missing comments remain distinct", () => {
  const outputs = frameioOutputs().slice(0, 2);
  outputs[1].provider_result.complete = false;
  assert.equal(frameioReviewResult(outputs).files[0].commentsComplete, false);
  assert.equal(frameioReviewResult(outputs.slice(0, 1)).files[0].commentCount, null);
  outputs[1].provider_result.complete = true;
  outputs[1].provider_result.comment_count = 1;
  assert.equal(frameioReviewResult(outputs).files[0].commentsComplete, false);
  outputs[1].provider_result.asset_id = account;
  outputs[1].provider_result.version_id = account;
  outputs[1].provider_result.file.id = account;
  assert.equal(frameioReviewResult(outputs).files.length, 2);
  assert.equal(frameioReviewResult(outputs).files[0].comments, undefined);
});

test("an explicit different deliverable keeps its main result", () => {
  const other = { step_key: "deliverable", operation: "docs.create" };
  assert.equal(frameioReviewResult([...frameioOutputs(), other], other), null);
});

test("follow-up prompts keep exact Frame.io identities and read evidence dependencies", () => {
  const result = frameioReviewResult(frameioOutputs());
  const prompt = resultRevisionPrompt({ result, instruction: "Make the checklist shorter." });
  assert.ok(prompt.includes(account) && prompt.includes(file));
  assert.match(prompt, /frameio\.file\.get.*frameio\.comments\.list/);
  assert.match(prompt, /all_succeeded/);
  assert.match(prompt, /\{\{steps.KEY\}\}/);
  assert.match(prompt, /Make the checklist shorter\./);
  assert.doesNotMatch(prompt, /gmail|pageproof|google docs/i);
  assert.equal(resultRevisionPrompt({ result, instruction: " " }), "");
});

test("native links cannot redirect to another asset, origin or credential URL", () => {
  assert.equal(frameioAppUrl(receipt.file.view_url, file), receipt.file.view_url);
  for (const url of [receipt.file.view_url + "?token=private", receipt.file.view_url.replace("next.frame.io", "evil.example"),
    `https://next.frame.io.evil.example/view/${file}`, `javascript:alert(1)`, `https://next.frame.io/view/${account}`]) {
    assert.equal(frameioAppUrl(url, file), null);
  }
});


test("a report revision preserves the full report without repeating its raw source bundle", () => {
  const body = "Source-backed analysis with prices, formulas and caveats. ".repeat(230)
    + "\n[product] https://example.com/serum; observed 2026-11-05";
  const entry = { operation: "report.compose", stepKey: "analysis",
    inputs: { sources: [{ id: "product", title: "Product page", content: "raw page evidence ".repeat(5000) }] } };
  const before = structuredClone(entry);
  const result = { kind: "report", provider: "aura", title: "Complete analysis", preview: { body } };
  const prompt = resultRevisionPrompt({ instruction: "Update and format the existing Google Sheet.",
    result, entry, runId: "saved-run" });
  assert.ok(prompt.length < 20_000);
  const context = JSON.parse(prompt.split("Saved result context (reference data): ")[1].split("\nPreserve the selected")[0]);
  assert.equal(context.body, body);
  assert.equal(context.runId, "saved-run");
  assert.equal(context.sourceStepKey, "analysis");
  assert.equal(context.inputs, null);
  assert.deepEqual(entry, before);
  for (const other of [{ ...result, kind: "spreadsheet" }, { ...result, preview: {} }]) {
    const retained = resultRevisionPrompt({ instruction: "Review this result", result: other, entry });
    assert.ok(retained.includes("raw page evidence"));
  }
});
