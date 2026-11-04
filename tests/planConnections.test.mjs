import test from "node:test";
import assert from "node:assert/strict";
import { buildPlanConnectionTools } from "../src/lib/planConnections.mjs";

const sheets = { tool: "Google Sheets", toolSlug: "google", operation: "sheets.append",
  iWill: "update the spreadsheet", flow: [{ label: "Uses", value: "Google Sheets" }] };
const drive = { tool: "Google Drive", toolSlug: "google", operation: "drive.files.search",
  iWill: "find the source file" };
const requirement = (permissions, provider = "google") => ({
  provider_hint: provider, capability: provider, canonical_provider: "google",
  status: "required", reason: `Authorize exact operations for ${provider}`,
  required_permissions: permissions,
});

test("a shared Google connector needing Sheets permission produces one Sheets access prompt", () => {
  const tools = buildPlanConnectionTools([sheets], {
    connectionChecklist: [requirement(["sheets.append", "sheets.workbook.get"])],
  });
  assert.equal(tools.length, 1);
  assert.equal(tools[0].name, "Google Sheets");
  assert.equal(tools[0].provider, "google");
  assert.equal(tools[0].accessNeeded, true);
});

test("Run without Google Drive rebuilds a Sheets-only checklist from the revised plan", () => {
  const original = buildPlanConnectionTools([drive, sheets], {
    connectionChecklist: [requirement(["drive.files.search"])],
  });
  assert.deepEqual(original.map((tool) => tool.name), ["Google Drive", "Google Sheets"]);
  const revised = buildPlanConnectionTools([sheets], {
    connectionChecklist: [requirement(["sheets.append"])],
  });
  assert.deepEqual(revised.map((tool) => tool.name), ["Google Sheets"]);
  assert.equal(revised[0].accessNeeded, true);
  assert.deepEqual(original.map((tool) => tool.name), ["Google Drive", "Google Sheets"]);
});

test("a Sheets-only connection gate is named correctly even before visible steps are available", () => {
  const tools = buildPlanConnectionTools([], {
    connectionChecklist: [requirement(["sheets.campaign_report.create", "sheets.campaign_report.get"], "google-workspace")],
  });
  assert.deepEqual(tools.map((tool) => tool.name), ["Google Sheets"]);
  assert.equal(tools[0].provider, "google-workspace");
});

test("app labels preserve the executable route and do not merge separate Sheets connectors", () => {
  const tools = buildPlanConnectionTools([
    sheets, { ...sheets, toolSlug: "google-sheets" },
  ], { connectionChecklist: [requirement(["sheets.append"])] });
  assert.deepEqual(tools.map((tool) => tool.provider), ["google", "google-sheets"]);
  assert.notEqual(tools[0].key, tools[1].key);
});

test("satisfied requirements and removed apps do not reappear in a ready revised plan", () => {
  const tools = buildPlanConnectionTools([sheets], {
    connectionChecklist: [{ ...requirement(["drive.files.search"]), status: "satisfied" }],
  });
  assert.deepEqual(tools.map((tool) => tool.name), ["Google Sheets"]);
  assert.equal(Boolean(tools[0].accessNeeded), false);
});

for (const [name, operation] of [
  ["Gmail", "gmail.get"], ["Google Calendar", "calendar.get"],
  ["Google Docs", "docs.get"], ["Google Drive", "drive.files.search"],
]) {
  test(`${name} permissions keep their existing checklist label`, () => {
    const tools = buildPlanConnectionTools([], { connectionChecklist: [requirement([operation])] });
    assert.deepEqual(tools.map((tool) => tool.name), [name]);
  });
}
