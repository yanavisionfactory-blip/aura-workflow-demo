import test from "node:test";
import assert from "node:assert/strict";

import { isVerifiedConnection, selectConnection } from "../src/lib/connectionSelection.mjs";

test("selects the exact account by stable connection id", () => {
  const tools = [
    { id: "first", slug: "slack", display_name: "Slack" },
    { id: "selected", slug: "slack", display_name: "Slack" },
  ];
  assert.equal(
    selectConnection(tools, { toolName: "Slack", provider: "slack", connectionId: "selected" }).id,
    "selected"
  );
});

test("never guesses when multiple accounts are ambiguous", () => {
  const tools = [
    { id: "first", slug: "slack", display_name: "Slack" },
    { id: "second", slug: "slack", display_name: "Slack" },
  ];
  assert.throws(
    () => selectConnection(tools, { toolName: "Slack", provider: "slack" }),
    /Choose which Slack account/
  );
});

test("requires explicit provider verification before reporting readiness", () => {
  assert.equal(isVerifiedConnection({ status: "verified", verification: { ok: true } }), true);
  assert.equal(isVerifiedConnection({ status: "verified", verification: { ok: false } }), false);
  assert.equal(isVerifiedConnection({ status: "verification_pending" }), false);
});
