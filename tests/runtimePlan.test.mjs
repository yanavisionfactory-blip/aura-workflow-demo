import test from "node:test";
import assert from "node:assert/strict";

import { hasDurablePlan, planningRequestPrompt, restorablePlanningRun, savedRunResumeView, sameExecutablePlan, unmatchedWriteTools, shouldRestoreRememberedRun, savedRunActionLocation, workflowInputPrompt } from "../src/lib/runtimePlan.mjs";

test("a delayed remembered run cannot replace a newly selected workflow", async () => {
  let finishRead;
  const read = new Promise((resolve) => { finishRead = resolve; });
  let selectedRun = "old-run";
  let generation = 0;
  let view = "input";
  const startedAtGeneration = generation;
  const restore = read.then(() => {
    if (shouldRestoreRememberedRun({ rememberedRunId: "old-run", currentRememberedRunId: selectedRun,
      startedAtGeneration, currentGeneration: generation })) view = "old-plan";
  });
  generation += 1;
  selectedRun = null;
  finishRead();
  await restore;
  assert.equal(view, "input");
  const selection = { rememberedRunId: "saved", currentRememberedRunId: "saved",
    startedAtGeneration: 2, currentGeneration: 2 };
  assert.equal(shouldRestoreRememberedRun(selection), true);
  assert.equal(shouldRestoreRememberedRun({ ...selection, hasCurrentIntent: true }), false);
});

test("Run again and suggested next retain their exact task in the normal input", () => {
  const prompt = "Prepare a roofing proposal.\nKeep every placement unpublished.";
  const next = savedRunActionLocation(prompt);
  assert.equal(next.pathname, "/");
  assert.equal(next.state.newWorkflow, true);
  assert.equal(workflowInputPrompt({ state: next.state }), prompt);
  assert.deepEqual(Object.keys(next.state).sort(), ["newWorkflow", "workflowPrompt"]);
  assert.equal(workflowInputPrompt({ state: savedRunActionLocation(null).state }), "");
});

test("task links prefill only text and cannot carry approval or execution state", () => {
  const prompt = "Review Classic Roofing & return a draft.\nDo not publish.";
  const search = `?prompt=${encodeURIComponent(prompt)}&approve=true&run=existing&accountId=123`;
  assert.equal(workflowInputPrompt({ search }), prompt);
  assert.equal(workflowInputPrompt({ search: "?approve=true&run=existing" }), "");
  assert.equal(workflowInputPrompt({ state: { workflowPrompt: "Reviewed text" }, search }), "Reviewed text");
  assert.equal(workflowInputPrompt({ search: `?prompt=${"x".repeat(20001)}` }), "");
});

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

test("revisions preserve the executable provider instead of its display label", () => {
  for (const provider of [{ tool_slug: "google" }, { toolSlug: "google" }]) {
    const prompt = planningRequestPrompt("Save a review draft", "Omit LinkedIn", [
      { tool: "Google Docs", ...provider, operation: "docs.create", consequential: true },
    ]);
    assert.match(prompt, /"tool":"google","operation":"docs.create"/);
    assert.doesNotMatch(prompt, /"tool":"Google Docs"/);
  }
});


test("refresh restores a tool-output checkpoint before any later write approval", () => {
  const run = { id: "run", status: "awaiting_approval", plan_approved: true,
    plan: { steps: [{ key: "draft" }, { key: "save" }] },
    tool_output_review: { step_id: "draft", step_ids: ["draft"] },
    steps: [{ id: "draft", status: "completed" }, { id: "save", approval_status: "pending", approval_preview: { status: "ready" } }],
  };
  assert.equal(savedRunResumeView(run), "execution");
  delete run.tool_output_review;
  assert.equal(savedRunResumeView(run), "preview");
});
