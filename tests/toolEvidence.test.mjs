import test from "node:test";
import assert from "node:assert/strict";
import { toolEvidence, redactEvidence } from "../src/lib/toolEvidence.mjs";

test("per-tool evidence retains MCP rows and errors without converting missing results into zero", () => {
  const rows = [{ keyword: "title payoff", position: 0, volume: null }];
  const activity = [{ id: "sem", tool: "agent-semrush-3ee21ac09f", status: "completed", output: { operation: "mcp.call", resolved_arguments: { domain: "example.com" }, provider_result: { content: [{ type: "text", text: JSON.stringify(rows) }], isError: true } } }, { id: "site", tool: "Sitebulb", status: "blocked", error: "No completed audit supplied" }];
  const before = JSON.stringify(activity);
  const evidence = toolEvidence(activity);
  assert.equal(evidence[0].tool, "Semrush");
  assert.equal(evidence[0].status, "provider_error");
  assert.deepEqual(evidence[0].response.content[0], rows);
  assert.equal(evidence[1].hasResponse, false);
  assert.equal(evidence[1].response, null);
  assert.equal(JSON.stringify(activity), before);
});

test("saved inputs and nested responses redact secrets while retaining legitimate metric keys", () => {
  const value = { api_key: "SECRET", nested: [{ Authorization: "Bearer SECRET", backlinks: 82, key: "T01", url: "https://example.com/?access_token=SECRET&domain=client.com" }], text: "Bearer ABC.xyz" };
  const safe = redactEvidence(value);
  assert.doesNotMatch(JSON.stringify(safe), /SECRET|ABC.xyz/);
  assert.equal(safe.nested[0].backlinks, 82);
  assert.equal(safe.nested[0].key, "T01");
});

test("connector debug JSON strings cannot reveal cookies or credentials", () => {
  const response = { error: { message: "Insufficient plan" }, os: [{ msg: '[debug] err.response {"status":403,"headers":{"set-cookie":"SECRET","Authorization":"Bearer PRIVATE"},"data":{"error":"Insufficient plan"}}' }] };
  const view = toolEvidence([{ tool: "Ahrefs", status: "completed", output: { provider_result: response } }])[0];
  assert.equal(view.status, "provider_error");
  assert.match(JSON.stringify(view.response), /Insufficient plan/);
  assert.doesNotMatch(JSON.stringify(view.response), /SECRET|PRIVATE/);
});
