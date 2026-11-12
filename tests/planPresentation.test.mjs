import assert from "node:assert/strict";
import test from "node:test";

import { operationStepTitle, videoReviewPlanContent, weatherStepTitle } from "../src/lib/planPresentation.mjs";

test("video operations describe the production review despite generic planner reasons", () => {
  for (const operation of ["frameio.video.review", "intelligence.video.review"]) {
    for (const reason of ["Identify errors and collect timestamped findings", "Verify the saved result", "Run the required primary review"]) {
      const step = Object.freeze({ operation, reason, arguments: Object.freeze({ file_id: "exact-version", instructions: "Review this video carefully" }) });
      const before = structuredClone(step);
      const content = videoReviewPlanContent(step);
      assert.equal(operationStepTitle(step), "Review the video and prepare production feedback");
      assert.match(content.iWill, /full timeline.*sampled frames and audio/);
      assert.match(content.iWill, /spelling mistakes, audio problems, and visual distractions/);
      assert.match(content.iWill, /chronological order with timestamps, observed issues, and recommended production fixes/);
      assert.match(content.iWill, /brief defects may be missed and audio times are approximate/);
      assert.deepEqual(step, before);
    }
  }
  assert.match(videoReviewPlanContent({ operation: "frameio.video.review" }).iWill, /selected Frame.io video version/);
  assert.match(videoReviewPlanContent({ operation: "intelligence.video.review" }).iWill, /uploaded video/);
});

test("account checks and comment reads are never presented as video analysis", () => {
  const identity = { operation: "frameio.identity.get", reason: "Verify the connected identity" };
  assert.equal(operationStepTitle(identity), "Check the connected Frame.io account");
  for (const operation of ["frameio.identity.get", "frameio.accounts.list", "frameio.file.get", "frameio.comments.list", "report.compose"]) {
    assert.equal(videoReviewPlanContent({ operation, reason: "Review video errors" }), null);
  }
  assert.equal(operationStepTitle({ operation: "frameio.comments.list" }, "Frame.io"), "Read from Frame.io");
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
