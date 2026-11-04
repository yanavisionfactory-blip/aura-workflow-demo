import test from "node:test";
import assert from "node:assert/strict";
import { alternativePlanConnection, planConnectionRevision } from "../src/lib/planConnectionRoutes.mjs";

const tool = { name: "Google Sheets", provider: "google" };
const entry = { name: "Google Sheets", provider: "google-sheets", connectable: true,
  preferredConnection: true, connectionBackend: "pipedream",
  routes: [{ provider: "google-sheets", connectable: true }] };

test("a blocked shared Google plan offers only the released dedicated app route", () => {
  assert.equal(alternativePlanConnection(tool, [entry]), "google-sheets");
  assert.equal(alternativePlanConnection({ ...tool, provider: "google-sheets" }, [entry]), null);
  for (const change of [{ connectable: false }, { preferredConnection: false },
    { connectionBackend: "nango" }, { provider: "unreleased" }, { routes: [] }]) {
    assert.equal(alternativePlanConnection(tool, [{ ...entry, ...change }]), null);
  }
  assert.equal(alternativePlanConnection({ name: "Google Drive", provider: "google" }, [entry]), null);
});

test("switching creates a review instruction and preserves other explicit route choices", () => {
  const current = { docs: "google-docs" };
  const revision = planConnectionRevision(tool, "google-sheets", current);
  assert.deepEqual(revision.connectionRoutes, { docs: "google-docs", sheets: "google-sheets" });
  assert.deepEqual(current, { docs: "google-docs" });
  assert.match(revision.instruction, /review before any external action/);
  assert.match(revision.instruction, /verification read/);
  assert.throws(() => planConnectionRevision(tool, "google"), /not available/);
});
