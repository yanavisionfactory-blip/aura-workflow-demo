import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  isManagedOAuthTool,
  managedOAuthProviderFor,
  userConnectionRoute,
} from "../src/lib/connectionPolicy.mjs";

test("HubSpot always routes to backend-owned OAuth", () => {
  assert.equal(managedOAuthProviderFor("HubSpot"), "hubspot");
  assert.deepEqual(userConnectionRoute("HubSpot"), {
    kind: "managed_oauth",
    provider: "hubspot",
  });
});

test("normal users never fall through to API, MCP, or interface setup", () => {
  for (const tool of ["Salesforce", "Meta Ads", "Creator Approvals", "Internal CRM"]) {
    assert.equal(isManagedOAuthTool(tool), false);
    assert.deepEqual(userConnectionRoute(tool), {
      kind: "backstage_only",
      provider: null,
    });
  }
});

test("normal workflow surfaces do not mount technical connector dialogs", () => {
  for (const file of [
    "src/components/aura/ConnectionsPill.jsx",
    "src/components/aura/ResourceComposer.jsx",
    "src/components/aura/CommandInput.jsx",
    "src/components/aura/PlanView.jsx",
  ]) {
    const source = readFileSync(new URL(`../${file}`, import.meta.url), "utf8");
    assert.equal(source.includes("ConnectToolModal"), false, file);
    assert.equal(source.includes("AuraInterfaceConnect"), false, file);
    assert.equal(source.includes("aura:open-connections"), false, file);
  }
});
