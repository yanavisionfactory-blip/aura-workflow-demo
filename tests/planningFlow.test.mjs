import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  approvalStartFailure,
  planningConnectionRequirements,
  planningConnectionsEnabled,
  planningDisposition,
  promptConnectionRequirements,
  shouldStartFreshPlanningRun,
} from "../src/lib/planningFlow.mjs";

test("a rejected Start request stays on the reviewable plan", () => {
  assert.deepEqual(
    approvalStartFailure(
      {
        status: "awaiting_approval",
        blocker: { code: "plan_approval_required" },
        plan: { steps: [{ operation: "weather.forecast" }] },
      },
      { status: 422, message: "Plan failed authorization" },
    ),
    { status: 422, message: "Plan failed authorization" },
  );
  assert.equal(
    approvalStartFailure(
      { status: "waiting_for_action", blocker: { code: "connection_required" } },
      { status: 409 },
    ),
    null,
  );
});

test("a completed backend plan proceeds to user review", () => {
  assert.equal(planningDisposition({
    status: "awaiting_approval",
    plan: { steps: [{ operation: "sheets.read" }] },
  }), "review");
});

test("pre-execution blockers cannot manufacture an executable fallback", () => {
  for (const status of ["blocked", "failed", "cancelled"]) {
    assert.equal(planningDisposition({ status }), "unavailable");
  }
  assert.equal(planningDisposition({ status: "waiting_for_action" }), "unavailable");
});

test("a missing provider becomes an actionable connection state", () => {
  const run = {
    status: "waiting_for_action",
    result: {
      status: "waiting_for_connection",
      missing_capabilities: ["meta-ads", "meta-ads"],
    },
    blocker: { code: "connection_required", tool_slug: "meta-ads" },
  };
  assert.equal(planningDisposition(run), "connection");
  assert.deepEqual(planningConnectionRequirements(run), ["meta-ads"]);
});

test("the connection checklist preserves every unsatisfied provider", () => {
  const run = {
    status: "waiting_for_action",
    connection_requirements: [
      { canonical_provider: "linear", status: "required" },
      { canonical_provider: "slack", status: "required" },
      { canonical_provider: "notion", status: "satisfied" },
    ],
    result: {
      status: "waiting_for_connection",
      missing_capabilities: ["linear", "slack"],
    },
  };

  assert.equal(planningDisposition(run), "connection");
  assert.deepEqual(planningConnectionRequirements(run), ["linear", "slack"]);
});

test("unfinished durable planning remains in background wait state", () => {
  for (const status of ["queued", "planning", "recovering", undefined]) {
    assert.equal(planningDisposition({ status }), "wait");
  }
});

test("the UI renders a language plan while durable compilation is still running", () => {
  const source = readFileSync(
    new URL("../src/pages/Demo.jsx", import.meta.url),
    "utf8",
  );
  const planViewSource = readFileSync(
    new URL("../src/components/aura/PlanView.jsx", import.meta.url),
    "utf8",
  );

  assert.equal(source.includes("instantLanguagePlan(confirmedIntent"), true);
  assert.equal(source.includes("languageDraftPrompt(confirmedIntent"), true);
  assert.equal(source.includes("Executable planning unavailable; the language plan remains visible"), true);
  assert.equal(planViewSource.includes("Connections never block plan creation"), true);
  assert.equal(planViewSource.includes("validatingExecution || missingTools.length"), true);
  assert.equal(source.includes('.replace(/^i\\s+will\\s+/i, "")'), true);
  assert.equal(source.includes("iWill: firstPersonStepCopy(step.iWill || step.reason)"), true);
});

test("Start uses combined approval unless staged action review is explicitly enabled", () => {
  const source = readFileSync(
    new URL("../src/pages/Demo.jsx", import.meta.url),
    "utf8",
  );
  const api = readFileSync(
    new URL("../src/lib/auraApi.js", import.meta.url),
    "utf8",
  );

  assert.equal(source.includes("VITE_STAGED_ACTION_REVIEW_ENABLED"), true);
  assert.equal(source.includes("const requiresReview = STAGED_ACTION_REVIEW_ENABLED"), true);
  assert.match(api, /approvePythonPlan\(runId, editedSteps = null, approveConsequential = true\)/);
});

test("the first prompt submission opens the language plan without a confirmation gate", () => {
  const source = readFileSync(
    new URL("../src/pages/Demo.jsx", import.meta.url),
    "utf8",
  );
  const submitStart = source.indexOf("const handleSubmit = useCallback");
  const submitEnd = source.indexOf("const startAlternativePlan", submitStart);
  const submitSource = source.slice(submitStart, submitEnd);

  assert.ok(submitStart >= 0 && submitEnd > submitStart);
  assert.equal(submitSource.includes("handleConfirmRef.current?.(prompt)"), true);
  assert.equal(submitSource.includes('setPhase("confirm")'), false);
  assert.equal(submitSource.includes('setPhase("plan")'), true);
});

test("an internal terminal state stays behind the run supervisor", () => {
  for (const status of ["failed", "blocked"]) {
    assert.equal(planningDisposition({
      status,
      public_status: "recovering",
      supervisor_state: { owner: "run_supervisor", status: "background_attention" },
    }), "wait");
  }
});

test("an explicitly named disconnected provider becomes a connection requirement", () => {
  assert.deepEqual(
    promptConnectionRequirements(
      "Build a report from Facebook Ads and send it with Gmail",
      [
        { name: "Meta Ads", slug: "meta-ads" },
        { name: "Gmail", slug: "gmail" },
      ],
      { Gmail: true, "Meta Ads": false }
    ),
    ["meta-ads"]
  );
});

test("generic intent does not guess a provider", () => {
  assert.deepEqual(
    promptConnectionRequirements(
      "Email a weekly advertising report",
      [{ name: "Meta Ads", slug: "meta-ads" }, { name: "Gmail", slug: "gmail" }],
      {}
    ),
    []
  );
});

test("a stopped validation never leaves the connection action spinning", () => {
  assert.equal(planningConnectionsEnabled("validating"), false);
  assert.equal(planningConnectionsEnabled("waiting_for_connection"), true);
  assert.equal(planningConnectionsEnabled("blocked"), true);
});

test("connection mode preserves the compiled plan instead of replacing it with an empty screen", () => {
  const source = readFileSync(
    new URL("../src/pages/Demo.jsx", import.meta.url),
    "utf8",
  );

  assert.equal(source.includes("...uiPlanFromRun(run)"), true);
  assert.equal(source.includes("pythonPlanRef.current = run.plan || null"), true);
});

test("an edited confirmed intent cannot reuse the previous durable planning request", () => {
  assert.equal(shouldStartFreshPlanningRun({
    nextIntent: "Read Notion notes and create Jira tasks",
    activeIntent: "Make a Canva deck about Munich weather",
    hasActiveRequest: true,
  }), true);
  assert.equal(shouldStartFreshPlanningRun({
    nextIntent: "  Read Notion notes and create Jira tasks. ",
    activeIntent: "read notion notes and create jira tasks",
    hasActiveRequest: true,
  }), false);
  assert.equal(shouldStartFreshPlanningRun({
    nextIntent: "Read Notion notes",
    activeIntent: "Read Notion notes",
    hasActiveRequest: true,
    revisionInstruction: "Use Jira for the output",
  }), true);
});
