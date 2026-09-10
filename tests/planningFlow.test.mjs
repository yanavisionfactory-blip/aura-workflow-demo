import test from "node:test";
import assert from "node:assert/strict";

import {
  planningConnectionRequirements,
  planningDisposition,
  promptConnectionRequirements,
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

test("unfinished planning remains on the plan loader", () => {
  for (const status of ["queued", "planning", "recovering", undefined]) {
    assert.equal(planningDisposition({ status }), "wait");
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
