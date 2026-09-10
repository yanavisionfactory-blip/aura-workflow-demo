import test from "node:test";
import assert from "node:assert/strict";

import { planningDisposition } from "../src/lib/planningFlow.mjs";

test("a completed backend plan proceeds to user review", () => {
  assert.equal(planningDisposition({
    status: "awaiting_approval",
    plan: { steps: [{ operation: "sheets.read" }] },
  }), "review");
});

test("pre-execution blockers fall back to editable plan creation", () => {
  for (const status of ["waiting_for_action", "blocked", "failed", "cancelled"]) {
    assert.equal(planningDisposition({ status }), "fallback");
  }
});

test("unfinished planning remains on the plan loader", () => {
  for (const status of ["queued", "planning", "recovering", undefined]) {
    assert.equal(planningDisposition({ status }), "wait");
  }
});
