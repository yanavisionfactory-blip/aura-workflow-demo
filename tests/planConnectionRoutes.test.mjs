import test from "node:test";
import assert from "node:assert/strict";
import { alternativePlanConnection, planConnectionRevision } from "../src/lib/planConnectionRoutes.mjs";

const tool = { name: "Google Sheets", provider: "google" };
const entry = { name: "Google Sheets", provider: "google-sheets", connectable: true,
  preferredConnection: true, connectionBackend: "pipedream",
  routes: [{ provider: "google-sheets", connectionBackend: "pipedream", connectable: true }] };

test("a blocked shared Google plan offers only the released dedicated app route", () => {
  assert.equal(alternativePlanConnection(tool, [entry]), "google-sheets");
  assert.equal(alternativePlanConnection({ ...tool, provider: "google-sheets" }, [entry]), null);
  for (const change of [{ connectable: false }, { routes: [] },
    { routes: [{ provider: "google-sheets", connectionBackend: "nango", connectable: true }] },
    { routes: [{ provider: "unreleased", connectionBackend: "pipedream", connectable: true }] },
    { routes: [{ provider: "google-sheets", connectionBackend: "pipedream", connectable: false }] }]) {
    assert.equal(alternativePlanConnection(tool, [{ ...entry, ...change }]), null);
  }
  assert.equal(alternativePlanConnection({ name: "Google Drive", provider: "google" }, [entry]), null);
});

test("a released alternative does not need to be the catalog's default connection", () => {
  assert.equal(alternativePlanConnection(tool, [{ ...entry, preferredConnection: false }]), "google-sheets");
  assert.equal(alternativePlanConnection(tool, [{ ...entry, provider: "google",
    preferredConnection: false, connectionBackend: "nango",
    routes: [{ provider: "google", connectionBackend: "nango", connectable: true }, ...entry.routes],
  }]), "google-sheets");
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
