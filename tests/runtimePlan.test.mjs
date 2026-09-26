import test from "node:test";
import assert from "node:assert/strict";

import { hasDurablePlan, planningRequestPrompt, restorablePlanningRun, savedRunResumeView, sameExecutablePlan, unmatchedWriteTools } from "../src/lib/runtimePlan.mjs";

test("execution requires both a durable run id and executable backend steps", () => {
  assert.equal(hasDurablePlan("run-1", { steps: [{ operation: "sheets.read" }] }), true);
  assert.equal(hasDurablePlan(null, { steps: [{ operation: "sheets.read" }] }), false);
  assert.equal(hasDurablePlan("run-1", { steps: [] }), false);
  assert.equal(hasDurablePlan("run-1", null), false);
});

test("only an unapproved review or connection wait reopens after a page refresh", () => {
  const waiting = { status: "waiting_for_action", plan_approved: false,
    connection_requirements: [{ status: "missing", capability: "mailchimp.audiences.list" }] };
  assert.equal(restorablePlanningRun(waiting), true);
  assert.equal(restorablePlanningRun({ status: "awaiting_approval", plan: { steps: [{ key: "slide" }] } }), true);
  assert.equal(restorablePlanningRun({ ...waiting, plan_approved: true }), false);
  assert.equal(restorablePlanningRun({ status: "running", plan: { steps: [{ key: "slide" }] } }), false);
  assert.equal(restorablePlanningRun({ status: "awaiting_approval", plan: { steps: [] } }), false);
});

test("reloading a durable run restores the prepared approval or observes execution without replay", () => {
  const run = { id: "run-1", plan_approved: true, status: "awaiting_approval",
    plan: { steps: [{ key: "send", operation: "gmail.send" }] },
    steps: [{ approval_status: "pending", approval_preview: { status: "ready",
      arguments: { to: "me", subject: "Today", body: "Prepared summary" } } }] };
  assert.equal(savedRunResumeView(run), "preview");
  assert.equal(savedRunResumeView({ ...run, steps: [] }), "execution");
  assert.equal(savedRunResumeView({ ...run, status: "running" }), "execution");
  assert.equal(savedRunResumeView({ ...run, status: "recovering" }), "execution");
  assert.equal(savedRunResumeView({ ...run, status: "completed" }), "execution");
  assert.equal(savedRunResumeView({ ...run, status: "waiting_for_action" }), "recovery");
  assert.equal(savedRunResumeView({ ...run, automation_state: { status: "blocked" } }), "recovery");
  assert.equal(savedRunResumeView({ ...run, plan_approved: false }), "plan");
  assert.equal(savedRunResumeView({ id: "run-2", status: "planning", plan_approved: false,
    inputs: {} }), "plan");
  assert.equal(savedRunResumeView({ id: "run-3", status: "waiting_for_action", plan_approved: false,
    blocker: { code: "planning_retry_required" } }), "plan");
  assert.equal(savedRunResumeView({ ...run, plan: { steps: [] } }), null);
});

test("a planner that ignores a requested edit cannot be presented as a revised plan", () => {
  const original = [{ tool_slug: "canva", operation: "canva.presentation.create", arguments: { phases: [{ title: "One" }] }, reason: "One slide" }];
  assert.equal(sameExecutablePlan(original, structuredClone(original)), true);
  assert.equal(sameExecutablePlan(original, [{ ...original[0], arguments: { phases: [{ title: "One" }, { title: "Two" }] } }]), false);
});

test("a hidden executable write cannot bypass the LLM plan the user reviewed", () => {
  const visible = [
    { tool: "AURA Intelligence", riskLevel: "read" },
    { tool: "Google Docs", riskLevel: "modify" },
    { tool: "Gmail", riskLevel: "read" },
  ];
  const compiled = [
    { tool_slug: "google", operation: "docs.create", consequential: true },
    { tool_slug: "google", operation: "gmail.send", consequential: true },
  ];
  const name = (step) => step.operation.startsWith("docs.") ? "Google Docs" : "Gmail";
  assert.deepEqual(unmatchedWriteTools(visible, compiled, name), ["Gmail"]);
  assert.deepEqual(unmatchedWriteTools(
    [...visible, { tool: "Gmail", riskLevel: "modify" }], compiled, name,
  ), []);
  assert.deepEqual(unmatchedWriteTools(
    [...visible, { tool: "Jira", riskLevel: "modify" }], compiled, name,
  ), ["Gmail", "Jira"]);
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
