import test from "node:test";
import assert from "node:assert/strict";

import { hasDurablePlan, planningRequestPrompt, sameExecutablePlan } from "../src/lib/runtimePlan.mjs";

test("execution requires both a durable run id and executable backend steps", () => {
  assert.equal(hasDurablePlan("run-1", { steps: [{ operation: "sheets.read" }] }), true);
  assert.equal(hasDurablePlan(null, { steps: [{ operation: "sheets.read" }] }), false);
  assert.equal(hasDurablePlan("run-1", { steps: [] }), false);
  assert.equal(hasDurablePlan("run-1", null), false);
});

test("a planner that ignores a requested edit cannot be presented as a revised plan", () => {
  const original = [{ tool_slug: "canva", operation: "canva.presentation.create", arguments: { phases: [{ title: "One" }] }, reason: "One slide" }];
  assert.equal(sameExecutablePlan(original, structuredClone(original)), true);
  assert.equal(sameExecutablePlan(original, [{ ...original[0], arguments: { phases: [{ title: "One" }, { title: "Two" }] } }]), false);
});

test("a requested plan change includes the reviewed actions and dependencies", () => {
  assert.equal(planningRequestPrompt("Send a report"), "Send a report");
  const prompt = planningRequestPrompt("Send a report", "Use Gmail instead of Slack", [
    { key: "read", tool_slug: "slack", operation: "slack.search", reason: "Read campaign figures" },
    { key: "send", tool_slug: "slack", operation: "slack.post", depends_on: ["read"], reason: "Share report" },
  ]);
  assert.match(prompt, /requested this change: Use Gmail instead of Slack/);
  assert.match(prompt, /"key":"send"/);
  assert.match(prompt, /"depends_on":\["read"\]/);
  assert.match(prompt, /do not repeat the previous plan unchanged/);
});
