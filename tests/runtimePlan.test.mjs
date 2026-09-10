import test from "node:test";
import assert from "node:assert/strict";

import { hasDurablePlan, planningRequestPrompt } from "../src/lib/runtimePlan.mjs";

test("execution requires both a durable run id and executable backend steps", () => {
  assert.equal(hasDurablePlan("run-1", { steps: [{ operation: "sheets.read" }] }), true);
  assert.equal(hasDurablePlan(null, { steps: [{ operation: "sheets.read" }] }), false);
  assert.equal(hasDurablePlan("run-1", { steps: [] }), false);
  assert.equal(hasDurablePlan("run-1", null), false);
});

test("a requested plan change becomes a new backend planning instruction", () => {
  assert.equal(planningRequestPrompt("Send a report"), "Send a report");
  assert.equal(
    planningRequestPrompt("Send a report", "Use Gmail instead of Slack"),
    "Send a report\n\nThe user reviewed the proposed workflow and requested this change: Use Gmail instead of Slack"
  );
});
