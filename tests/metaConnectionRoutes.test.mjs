import test from "node:test";
import assert from "node:assert/strict";
import { metaConnectionRows } from "../src/lib/metaConnectionRoutes.mjs";

const entry = { name: "Meta Ads", canonicalProvider: "meta-ads", routes: [
  { provider: "meta-ads-direct", connectable: true },
  { provider: "meta-ads-mcp", connectable: true },
] };
const pipeboard = { id: "pipeboard", slug: "agent-meta-ads-existing", canonical_provider: "meta-ads",
  base_url: "https://meta-ads.mcp.pipeboard.co/", enabled: true, status: "verified", verification: { ok: true } };

test("saved Pipeboard does not grant or block direct Meta; canonical catalog stays unchanged", () => {
  const rows = metaConnectionRows([entry], [pipeboard]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].displayName, "Meta Ads — Direct");
  assert.equal(rows[0].isConnected, false);
  assert.equal(rows[0].connectable, true);
  assert.equal(rows[0].connectionId, undefined);
  assert.equal(rows[1].displayName, "Meta Ads — Pipeboard");
  assert.equal(rows[1].connectionId, "pipeboard");
  assert.equal(rows[1].provider, pipeboard.slug);
  assert.equal(rows[1].isConnected, true);
  assert.equal(entry.routes.length, 2);
  assert.ok(rows.every((row) => row.name === "Meta Ads"));
});

test("disabled, failed and separate accounts remain manageable without claiming access", () => {
  const rows = metaConnectionRows([entry], [
    pipeboard, { ...pipeboard, id: "pipeboard-2", enabled: false },
    { ...pipeboard, id: "direct", slug: "meta-ads-direct", status: "degraded", verification: { ok: false } },
  ]);
  assert.equal(new Set(rows.map((row) => row.rowKey)).size, 3);
  assert.deepEqual(rows.map((row) => row.isConnected), [false, true, false]);
  assert.equal(rows[0].connectionId, "direct");
  assert.equal(rows[0].desc, "Check connection");
  assert.match(rows[2].desc, /Disabled/);
});

test("a saved grant remains manageable when catalog is unavailable; other brokers are not labelled Pipeboard", () => {
  const rows = metaConnectionRows([], [{ ...pipeboard, slug: "some-other-meta", base_url: "https://other.example" }], { includeSaved: true });
  assert.equal(rows[0].displayName, "Meta Ads — Other connection");
  assert.equal(rows[0].connectionId, pipeboard.id);
  assert.equal(rows[0].connectable, false);
  assert.deepEqual(metaConnectionRows([{ name: "Google Sheets" }], [pipeboard]), [{ name: "Google Sheets" }]);
});

test("an unconfigured direct route cannot acquire a Connect button from Pipeboard", () => {
  const rows = metaConnectionRows([{ ...entry, routes: [{ provider: "meta-ads-direct", connectable: false }, entry.routes[1]] }], [pipeboard]);
  assert.equal(rows[0].connectable, false);
  assert.equal(rows[0].isConnected, false);
});
