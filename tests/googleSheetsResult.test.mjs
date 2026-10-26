import test from "node:test";
import assert from "node:assert/strict";
import { columnName, googleSheetsResult, sheetAppLinks, sheetRange, spreadsheetId } from "../src/lib/googleSheetsResult.mjs";
import { primaryResultFromOutputs } from "../src/lib/resultPresentation.mjs";
import { mainToolEntry, toolResultEntries } from "../src/lib/toolResultViews.mjs";
import { operationStepTitle } from "../src/lib/planPresentation.mjs";
import { historyStepsForBackendRun } from "../src/lib/workflowHistory.mjs";

const read = (key, range, values, id = "workbook") => ({ step_key: key, operation: "sheets.read",
  resolved_arguments: { spreadsheet_id: id, range }, provider_result: { range, values,
    result_url: `https://docs.google.com/spreadsheets/d/${id}/edit` } });
const write = { step_key: "save", operation: "sheets.append", resolved_arguments: {
  spreadsheet_id: "workbook", range: "'Pilot Record'!A:B", values: [["Unverified requested text"]] },
  provider_result: { spreadsheetId: "workbook", updates: { updatedRange: "'Pilot Record'!A49:B52" } },
  outcome_check: { status: "verified" } };
const outputs = [read("source", "'Competitors'!A1:B2", [["Source data"]]), write,
  read("verify", "'Pilot Record'!A49:B52", [["Review", "Actual saved content"]])];

test("the final range, provider cells and exact verification step win over an earlier read of the same URL", () => {
  const primary = primaryResultFromOutputs(outputs, { title: "Pilot review" }, { primary_step_key: "verify" });
  assert.equal(primary.kind, "spreadsheet");
  assert.equal(primary.range, "'Pilot Record'!A49:B52");
  assert.equal(primary.sourceStepKey, "verify");
  assert.deepEqual(primary.ranges[0].values, [["Review", "Actual saved content"]]);
  assert.equal(primary.verified, true);
  assert.equal(new URL(primary.embedUrl).origin, "https://docs.google.com");
  const finalLink = sheetAppLinks(primary.spreadsheetId, primary.range, 123).link;
  assert.equal(new URLSearchParams(new URL(finalLink).hash.slice(1)).get("range"), "A49:B52");
  assert.equal(new URLSearchParams(new URL(finalLink).hash.slice(1)).get("gid"), "123");
  const entries = toolResultEntries(outputs.map((output) => ({ id: output.step_key,
    key: output.step_key, tool: "google", status: "completed", output })));
  assert.equal(mainToolEntry(entries, primary, { primary_step_key: "verify" }).id, "verify");
});

test("saved cells use retained independent readback, never the requested write values", () => {
  const result = googleSheetsResult([write]);
  assert.deepEqual(result.ranges, []);
  assert.doesNotMatch(JSON.stringify(result), /Unverified requested text/);
  const observed = { range: "'Pilot Record'!A49:B52", values: [["Verified body"]] };
  assert.deepEqual(googleSheetsResult([{ ...write, outcome_check: { status: "verified", observed } }]).ranges[0].values, observed.values);
  assert.deepEqual(googleSheetsResult([write, read("wrong", "'Other'!A1:B2", [["Wrong cells"]])]).ranges, []);
});

test("a source spreadsheet does not replace the requested report or an unrelated explicit result", () => {
  const report = { step_key: "report", operation: "report.compose", critic: { action: "accept" },
    outcome_check: { status: "verified" }, provider_result: { status: "draft", title: "Review", body: "Full report" } };
  assert.equal(primaryResultFromOutputs([outputs[0], report]).kind, "report");
  assert.equal(primaryResultFromOutputs([...outputs, report], {}, { primary_step_key: "report" }).provider, "ChatGPT");
  const another = read("other", "'Other'!A1:B2", [["Another workbook"]], "another");
  const result = googleSheetsResult([...outputs, another], {}, another);
  assert.equal(result.spreadsheetId, "another");
  assert.equal(result.range, "'Other'!A1:B2");
});

test("embed URLs never accept arbitrary hosts, credentials, script IDs or an error receipt", () => {
  for (const url of ["https://evil.test/spreadsheets/d/workbook/edit", "javascript:alert(1)",
    "https://docs.google.com.evil.test/spreadsheets/d/workbook/edit"]) {
    assert.equal(spreadsheetId({ provider_result: { result_url: url } }), null);
  }
  assert.equal(spreadsheetId({ resolved_arguments: { spreadsheet_id: "../bad?token=secret" } }), null);
  assert.equal(googleSheetsResult([{ ...write, provider_result: { error: "Failed", spreadsheetId: "workbook" } }]), null);
});

test("spreadsheet coordinates and sparse grid values preserve their row and column positions", () => {
  assert.deepEqual(sheetRange("'O''Reilly'!AA49:AB52"), { tab: "O'Reilly", row: 49, column: 26 });
  assert.equal(columnName(27), "AB");
  const result = googleSheetsResult([{ operation: "sheets.workbook.get", provider_result: {
    spreadsheetId: "workbook", sheets: [{ properties: { title: "Dashboard", sheetId: 4 }, data: [{ startRow: 7,
      startColumn: 1, rowData: [{ values: [{ effectiveValue: { numberValue: 0 } }, { effectiveValue: { boolValue: false } }] }] }] }] } }]);
  assert.equal(result.ranges[0].range, "'Dashboard'!B8");
  assert.deepEqual(result.ranges[0].values, [[0, false]]);
});

test("ChatGPT labels describe report generation without renaming unrelated AURA utilities", () => {
  assert.equal(operationStepTitle({ operation: "report.compose" }), "Generate report with ChatGPT");
  assert.equal(historyStepsForBackendRun({ plan: { steps: [{ tool_slug: "aura", operation: "report.compose" }] } })[0].tool, "ChatGPT");
  const entries = toolResultEntries([{ tool: "AURA Intelligence", operation: "report.compose", status: "completed" },
    { tool: "AURA Intelligence", operation: "weather.forecast", status: "completed" }]);
  assert.deepEqual(entries.map((entry) => entry.tool), ["ChatGPT", "AURA Intelligence"]);
});
