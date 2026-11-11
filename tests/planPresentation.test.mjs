import assert from "node:assert/strict";
import test from "node:test";

import { weatherStepTitle, operationStepTitle, videoReviewPlanContent, planStepGroups } from "../src/lib/planPresentation.mjs";
import { sameExecutablePlan } from "../src/lib/runtimePlan.mjs";

test("real video review is never presented as record search or saved-result verification", () => {
  for (const operation of ["frameio.video.review", "intelligence.video.review"]) {
    const step = { operation, reason: "Identify errors and collect timestamped findings" };
    const content = videoReviewPlanContent(step);
    assert.match(operationStepTitle(step), /Review the video/);
    assert.equal(content.phases.length, 3);
    assert.match(content.phases[0].description, /visuals and audio across the full timeline/);
    assert.match(content.phases[1].description, /spelling mistakes, audio problems/);
    assert.match(content.phases[2].description, /timestamp, issue, supporting observation, and recommended correction/);
    assert.match(content.timingNote, /sampled frames/);
    assert.match(content.timingNote, /Audio timestamps are approximate/);
  }
  assert.match(videoReviewPlanContent({ operation: "frameio.video.review" }).phases[0].description, /Frame.io video version/);
  assert.match(videoReviewPlanContent({ operation: "intelligence.video.review" }).phases[0].description, /uploaded video/);
  assert.equal(videoReviewPlanContent({ operation: "frameio.comments.list" }), null);
  assert.equal(operationStepTitle({ operation: "frameio.identity.get", reason: "Verify the connected identity" }), "Check the connected Frame.io account");
});

test("video preparation stays in the approved graph with exact file bindings and original edit indexes", () => {
  const original = [
    { key: "identity", operation: "frameio.identity.get", arguments: {}, riskLevel: "read" },
    { key: "video", operation: "frameio.video.review", depends_on: ["identity"],
      arguments: { account_id: "account", file_id: "exact-version", instructions: "Review this video" } },
    { key: "send", operation: "gmail.send", consequential: true, riskLevel: "modify", depends_on: ["video"] },
  ];
  const steps = structuredClone(original);
  for (const step of steps) Object.freeze(step);
  Object.freeze(steps);
  const { tasks, preparation } = planStepGroups(steps);
  assert.deepEqual(tasks.map(({ index }) => index), [1, 2]);
  assert.deepEqual(preparation.map(({ index }) => index), [0]);
  assert.strictEqual(tasks[0].step, steps[1]);
  assert.strictEqual(preparation[0].step, steps[0]);
  assert.equal(tasks[1].step.operation, "gmail.send");
  assert.equal(sameExecutablePlan(original, steps), true);
  assert.deepEqual(steps, original);
  assert.equal(planStepGroups(steps, false).tasks.length, 3);
});

test("standalone identity tasks and consequential or conditional steps remain in the main plan", () => {
  const identity = { key: "identity", operation: "frameio.identity.get" };
  const video = { key: "video", operation: "frameio.video.review" };
  assert.equal(planStepGroups([identity]).preparation.length, 0);
  for (const flags of [{ consequential: true }, { riskLevel: "modify" }, { condition: { field: "enabled" } }, { optional: true }]) {
    assert.equal(planStepGroups([{ ...identity, ...flags }, video]).preparation.length, 0);
  }
  assert.equal(planStepGroups([{ operation: "frameio.accounts.list" }, video]).preparation.length, 0);
  assert.equal(planStepGroups([{ operation: "frameio.comments.list" }, video]).preparation.length, 0);
});

test("weather titles reflect the requested day", () => {
  assert.equal(weatherStepTitle({ arguments: { date: "today" } }), "Check today's weather");
  assert.equal(
    weatherStepTitle({ arguments: { date: "tomorrow" } }),
    "Check tomorrow's weather",
  );
  assert.equal(
    weatherStepTitle({ arguments: { date: "2026-09-20" } }),
    "Check weather for 2026-09-20",
  );
  assert.equal(
    weatherStepTitle({ reason: "Read today's Berlin forecast" }),
    "Check today's weather",
  );
  assert.equal(weatherStepTitle({}), "Check the weather");
});
