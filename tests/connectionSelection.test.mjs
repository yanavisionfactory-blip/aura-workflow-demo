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

test("reuses one verified account across action and MCP routes", () => {
  const tools = [
    {
      id: "action",
      slug: "notion",
      canonical_provider: "notion",
      display_name: "Notion",
      external_account_id: "apn_shared",
      enabled: true,
      status: "verified",
    },
    {
      id: "mcp",
      slug: "notion-mcp",
      canonical_provider: "notion",
      display_name: "Notion",
      external_account_id: "apn_shared",
      enabled: true,
      status: "verified",
    },
  ];

  assert.equal(
    selectConnection(tools, { toolName: "Notion", provider: "notion-mcp" }).id,
    "mcp",
  );
});

test("calendar and documents can reuse the verified Google Workspace account", () => {
  const tools = [{
    id: "google-account", slug: "google", display_name: "Google Workspace",
    enabled: true, status: "verified", verification: { ok: true },
    allowed_operations: ["calendar.create", "docs.create", "gmail.send"],
  }];
  assert.equal(selectConnection(tools, { toolName: "Google Calendar", provider: "google-calendar" })?.id,
    "google-account");
  assert.equal(selectConnection(tools, { toolName: "Google Docs", provider: "google-docs" })?.id,
    "google-account");
});

test("Google Docs Manage selects its dedicated route even when Workspace is verified", () => {
  const tools = [
    { id: "workspace", slug: "google", display_name: "Google Workspace",
      enabled: true, status: "verified", allowed_operations: ["docs.create"] },
    { id: "docs", slug: "google-docs", display_name: "Google Docs",
      enabled: false, status: "degraded", allowed_operations: ["google-docs.create-document"] },
  ];
  assert.equal(selectConnection(tools, { toolName: "Google Docs", provider: "google" })?.id, "docs");
});

test("a Google account without calendar permission cannot satisfy Calendar", () => {
  const tools = [{ id: "gmail-only", slug: "google", display_name: "Google Workspace",
    allowed_operations: ["gmail.send", "docs.create"] }];
  assert.equal(selectConnection(tools, { toolName: "Google Calendar", provider: "google" }), null);
});
