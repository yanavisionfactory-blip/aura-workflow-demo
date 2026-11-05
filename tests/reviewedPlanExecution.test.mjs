import test from "node:test";
import assert from "node:assert/strict";
import { continueReviewedPlan, needsReviewedPlanResume } from "../src/lib/reviewedPlanExecution.mjs";
import { savedRunResumeView } from "../src/lib/runtimePlan.mjs";

const legacy = () => ({ id: "saved", plan_approved: true, status: "awaiting_approval",
  plan: { steps: [{ key: "draft" }, { key: "sheet" }, { key: "rows" }] },
  steps: [{ id: "draft", approval_id: "approval", approval_status: "pending",
    approval_preview: { status: "ready" } }],
});

test("a saved zero-progress run continues its original plan before showing any input preview", async () => {
  const run = legacy();
  const attempted = new Set();
  const calls = [];
  assert.equal(savedRunResumeView(run, { openPreview: true }), "execution");
  assert.equal(await continueReviewedPlan(run, async (...args) => calls.push(args), attempted), true);
  assert.deepEqual(calls, [["saved"]], "resumption sends no action approval, edited inputs or new plan");
  const resumed = { ...run, status: "running", execution_context: {
    __aura_tool_output_review__: { enabled: true, execute_reviewed_plan: true },
  } };
  assert.equal(await continueReviewedPlan(resumed, () => assert.fail("duplicate resume"), attempted), false);
  const output = { ...resumed, status: "awaiting_approval", tool_output_review: { step_id: "draft" } };
  assert.equal(await continueReviewedPlan(output, () => assert.fail("acknowledged output"), attempted), false);
  assert.equal(savedRunResumeView(output), "execution");
});

test("upgrading an older completed-result checkpoint does not acknowledge or edit its output", async () => {
  const run = { ...legacy(), tool_output_review: { step_id: "draft" },
    execution_context: { __aura_tool_output_review__: { enabled: true, reviewed_step_ids: [] } } };
  const before = structuredClone(run);
  const calls = [];
  assert.equal(await continueReviewedPlan(run, async (...args) => calls.push(args), new Set()), true);
  assert.deepEqual(run, before);
  assert.deepEqual(calls, [["saved"]]);
});

test("unstarted, unattended and recovering/terminal runs cannot enter the legacy resume path", () => {
  for (const change of [{ plan_approved: false }, { plan: null }, { id: null },
    { status: "cancelled" }, { status: "completed" }, { status: "waiting_for_action" },
    { status: "running" }, { status: "recovering" },
    { execution_context: { execution_mode: "unattended" } },
    { execution_context: { __aura_tool_output_review__: { execute_reviewed_plan: true } } }]) {
    assert.equal(needsReviewedPlanResume({ ...legacy(), ...change }), false);
  }
});

test("a failed or stale resume surfaces an error instead of looping or opening action approval", async () => {
  const attempts = new Set();
  const failure = Object.assign(new Error("The saved plan changed"), { status: 409 });
  await assert.rejects(continueReviewedPlan(legacy(), async () => { throw failure; }, attempts), failure);
  await assert.rejects(continueReviewedPlan(legacy(), () => assert.fail("unbounded retry"), attempts), /restore this saved run/);
});
