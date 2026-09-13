import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  planningConnectionRequirements,
  planningDisposition,
  promptConnectionRequirements,
  shouldStartFreshPlanningRun,
} from "../src/lib/planningFlow.mjs";

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

test("unfinished planning remains on the plan loader", () => {
  for (const status of ["queued", "planning", "recovering", undefined]) {
    assert.equal(planningDisposition({ status }), "wait");
  }
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
