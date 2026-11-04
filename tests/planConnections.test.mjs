import test from "node:test";
import assert from "node:assert/strict";
import { hasPlanConnectionGrant, planConnectionTools, requirementTools } from "../src/lib/planConnections.mjs";

const sheets = { key: "workbook", tool: "Google Sheets", toolSlug: "google",
  operation: "sheets.kpi.create", flow: [{ label: "Uses", value: "Google Sheets" }] };
const requirement = (permissions) => ({ provider_hint: "google", status: "required",
  reason: "Authorize exact operations for google", required_permissions: permissions });

test("a Sheets-only plan needing a shared Google grant has one Sheets row and no Drive requirement", () => {
  const tools = planConnectionTools([sheets], {
    connectionChecklist: [requirement(["sheets.kpi.create", "sheets.workbook.get"])],
    connectionRequirements: ["google"],
  });
  assert.deepEqual(tools.map(({ name, provider, accessNeeded }) => ({ name, provider, accessNeeded })),
    [{ name: "Google Sheets", provider: "google", accessNeeded: true }]);
  assert.equal(hasPlanConnectionGrant(tools[0], { slug: "google", allowed_operations: ["sheets.kpi.create"] }), false);
  assert.equal(hasPlanConnectionGrant(tools[0], { slug: "google", allowed_operations: ["sheets.kpi.create", "sheets.workbook.get"] }), true);
  assert.equal(hasPlanConnectionGrant(tools[0], { slug: "google-sheets", allowed_operations: tools[0].requiredPermissions }), false);
});

test("mixed shared-account grants expose only the apps actually required", () => {
  const tools = requirementTools(requirement(["sheets.append", "gmail.send", "calendar.get"]));
  assert.deepEqual(tools.map((tool) => tool.name), ["Google Sheets", "Gmail", "Google Calendar"]);
  assert.deepEqual(tools.map((tool) => tool.requiredPermissions), [["sheets.append"], ["gmail.send"], ["calendar.get"]]);
  assert.equal(requirementTools(requirement(["drive.files.search"]))[0].name, "Google Drive");
});

test("legacy Google requirements use reviewed operations rather than inventing Drive access", () => {
  assert.deepEqual(planConnectionTools([sheets], { connectionRequirements: ["google"] }).map((tool) => tool.name), ["Google Sheets"]);
  assert.equal(requirementTools("google")[0].name, "Google Workspace");
});

test("rebuilding without Drive removes its row while preserving Sheets", () => {
  const drive = { tool: "Google Drive", toolSlug: "google", operation: "drive.files.search" };
  assert.deepEqual(planConnectionTools([drive, sheets]).map((tool) => tool.name), ["Google Drive", "Google Sheets"]);
  assert.deepEqual(planConnectionTools([sheets], {
    connectionChecklist: [{ ...requirement(["drive.files.search"]), status: "satisfied" }],
  }).map((tool) => tool.name), ["Google Sheets"]);
});
