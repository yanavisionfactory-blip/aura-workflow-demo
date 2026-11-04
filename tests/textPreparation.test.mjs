import test from "node:test";
import assert from "node:assert/strict";
import { continueTextPreparation, pendingTextPreparation } from "../src/lib/textPreparation.mjs";
import { savedRunResumeView } from "../src/lib/runtimePlan.mjs";

const run = () => ({ id: "run", plan_approved: true, status: "awaiting_approval",
  plan: { steps: [{ key: "draft" }] }, steps: [{ id: "draft", status: "awaiting_approval",
    operation: "anthropic.chat", preparation_only: true, approval_id: "approval",
    approval_status: "pending", approval_preview: { status: "ready" } }] });

test("Start and restored runs generate certified text before displaying a review", async () => {
  const value = run();
  assert.equal(savedRunResumeView(value), "execution");
  assert.equal(savedRunResumeView(value, { openPreview: true }), "execution");
  const calls = [], attempted = new Set();
  const decide = async (...args) => calls.push(args);
  assert.equal(await continueTextPreparation(value, decide, attempted), true);
  assert.deepEqual(calls, [["approval", true]]); // no prompt edits or plan rewrite
  assert.equal(await continueTextPreparation(value, decide, attempted), false);
  assert.equal(calls.length, 1);
});

test("tool names and planner classifications never authorize external writes", () => {
  const value = run();
  delete value.steps[0].preparation_only;
  assert.equal(pendingTextPreparation(value), null);
  assert.equal(savedRunResumeView(value, { openPreview: true }), "preview");
  value.steps.unshift({ ...value.steps[0], id: "sheet", operation: "sheets.append" });
  value.steps[1].preparation_only = true;
  assert.equal(pendingTextPreparation(value), null);
});

test("only an unattempted pending request in an approved running workflow can advance", () => {
  for (const change of [
    (r) => { r.plan_approved = false; },
    (r) => { r.status = "failed"; },
    (r) => { r.tool_output_review = { step_id: "draft" }; },
    (r) => { r.steps[0].output = { provider_result: {} }; },
    (r) => { r.steps[0].status = "completed"; },
    (r) => { r.steps[0].approval_status = "approved"; },
    (r) => { r.steps[0].approval_preview.status = "preparing"; },
  ]) {
    const value = run(); change(value);
    assert.equal(pendingTextPreparation(value), null);
  }
});

test("a duplicate tab re-reads a decided approval once without replaying it", async () => {
  const attempted = new Set(); let calls = 0;
  const decide = async () => { calls++; throw Object.assign(new Error("Already decided"), { status: 409 }); };
  assert.equal(await continueTextPreparation(run(), decide, attempted), true);
  assert.equal(await continueTextPreparation(run(), decide, attempted), false);
  assert.equal(calls, 1);
});

test("generation failures surface to recovery rather than being presented as output", async () => {
  const failure = new Error("Connection unavailable");
  await assert.rejects(continueTextPreparation(run(), async () => { throw failure; }, new Set()), failure);
});
