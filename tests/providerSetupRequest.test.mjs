import test from "node:test";
import assert from "node:assert/strict";
import { sitebulbApprovalRequest } from "../src/lib/providerSetupRequest.mjs";

const issue = {
  code: "provider_registration_rejected", requires_provider_approval: true,
  provider_http_status: 400, endpoint: "https://mcp.sitebulb.com/cloud",
  callback_url: "https://aura.example.org/v1/oauth/mcp-agent/callback",
};

test("Sitebulb approval request carries the actual callback and read-only setup, without credentials", () => {
  const draft = sitebulbApprovalRequest({ ...issue, credential: "PRIVATE", message: "untrusted extra provider text" });
  assert.equal(draft.to, "support@sitebulb.com");
  assert.ok(draft.body.includes(issue.callback_url));
  assert.ok(draft.body.includes(issue.endpoint));
  assert.match(draft.body, /mcp:read/);
  assert.match(draft.body, /cannot start a crawl/);
  assert.match(draft.body, /do not activate a paid subscription/);
  assert.doesNotMatch(draft.body, /PRIVATE|untrusted extra provider text/);
});

test("ordinary connection failures do not become callback approval requests", () => {
  assert.equal(sitebulbApprovalRequest(null), null);
  assert.equal(sitebulbApprovalRequest({ ...issue, requires_provider_approval: false }), null);
  assert.equal(sitebulbApprovalRequest({ ...issue, endpoint: "https://another.example/mcp" }), null);
  assert.equal(sitebulbApprovalRequest({ ...issue, provider_http_status: 401 }), null);
});

test("setup drafts reject credential-bearing or non-public callback values", () => {
  for (const callback_url of [
    "http://aura.example.org/v1/oauth/mcp-agent/callback",
    "https://secret@aura.example.org/v1/oauth/mcp-agent/callback",
    "https://aura.example.org/v1/oauth/mcp-agent/callback?token=PRIVATE",
    "https://aura.example.org/v1/oauth/mcp-agent/callback#PRIVATE",
    "https://localhost/v1/oauth/mcp-agent/callback",
    "https://127.0.0.1/v1/oauth/mcp-agent/callback",
  ]) assert.equal(sitebulbApprovalRequest({ ...issue, callback_url }), null);
});
