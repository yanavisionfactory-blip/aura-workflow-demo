import test from "node:test";
import assert from "node:assert/strict";
import { columnName, googleSheetsResult, sheetAppLinks, sheetRange, spreadsheetId } from "../src/lib/googleSheetsResult.mjs";
import { primaryResultFromOutputs } from "../src/lib/resultPresentation.mjs";
import { mainToolEntry, toolOutputResult, toolResultEntries } from "../src/lib/toolResultViews.mjs";
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

test("Markdown headers come from the matching saved header read, never another workbook or tab", () => {
  const header = read("headers", "'Pilot Record'!A1:B1", [["Name", "Comparison"]]);
  assert.deepEqual(googleSheetsResult([header, ...outputs]).headers, ["Name", "Comparison"]);
  for (const wrong of [read("h", "'Other'!A1:B1", [["Wrong"]]), read("h", "'Pilot Record'!A1:B1", [["Wrong"]], "other"), read("h", "'Pilot Record'!B1:C1", [["Wrong"]])]) {
    assert.deepEqual(googleSheetsResult([wrong, ...outputs]).headers, []);
  }
});

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


const brokerWrite = (operation = "google-sheets.add-multiple-rows") => ({
  step_key: "save", operation,
  resolved_arguments: { sheetId: "broker-workbook", worksheetId: 173, rows: '[["Requested cells are not readback"]]' },
  provider_result: { os: [], ret: { spreadsheetId: "broker-workbook", updatedRange: "Dashboard!A1:G8",
    updatedRows: 8, updatedColumns: 7, updatedCells: 56 },
  exports: { $summary: "Successfully updated 8 row(s) in the spreadsheet." } },
});

const brokerRead = () => ({ step_key: "verify", operation: "google-sheets.read-rows",
  resolved_arguments: { spreadsheetId: "broker-workbook", sheetName: "Dashboard", range: "A1:G8", hasHeaders: false },
  provider_result: { os: [], ret: { rows: [["Revenue", "", "Not publicly reported", "Awaiting input"], ["Actual zero", 0, false, null]], rowCount: 2 } },
});

test("broker read-rows displays evaluated cells from the same written workbook and preserves unknowns and true zeros", () => {
  const outputs = [brokerWrite(), brokerRead()];
  const before = structuredClone(outputs);
  const result = googleSheetsResult(outputs);
  assert.equal(result.sourceStepKey, "verify");
  assert.equal(result.readBack, true);
  assert.equal(result.partialReadBack, false);
  assert.equal(result.verified, false);
  assert.equal(result.spreadsheetId, "broker-workbook");
  assert.equal(result.sheetId, 173);
  assert.deepEqual(result.ranges, [{ range: "'Dashboard'!A1:G8", values: outputs[1].provider_result.ret.rows }]);
  assert.doesNotMatch(JSON.stringify(result), /Requested cells are not readback/);
  assert.deepEqual(outputs, before);
});

test("broker readback rejects stale, other-workbook, other-tab, unrelated-range and header-object responses", () => {
  assert.deepEqual(googleSheetsResult([brokerRead(), brokerWrite()]).ranges, []);
  for (const args of [{ spreadsheetId: "other-workbook" }, { sheetName: "Other" }, { range: "H1:J8" },
    { range: "A9:G20" }, { range: "Other!A1:G8" }, { hasHeaders: true }, { hasHeaders: undefined }]) {
    const read = brokerRead();
    read.resolved_arguments = { ...read.resolved_arguments, ...args };
    assert.deepEqual(googleSheetsResult([brokerWrite(), read]).ranges, [], JSON.stringify(args));
  }
  const read = brokerRead();
  read.provider_result.ret.rows = [{ Metric: "Revenue", Actual: 0 }];
  assert.deepEqual(googleSheetsResult([brokerWrite(), read]).ranges, []);
});

test("a larger readback range and quoted tab names retain their actual coordinates", () => {
  const write = brokerWrite(), read = brokerRead();
  write.provider_result.ret.updatedRange = "'Brand''s Dashboard'!A2:G8";
  read.resolved_arguments = { ...read.resolved_arguments, sheetName: "Brand's Dashboard", range: "A1:G20" };
  const result = googleSheetsResult([write, read]);
  assert.equal(result.ranges[0].range, "'Brand''s Dashboard'!A1:G20");
  assert.equal(result.range, "'Brand''s Dashboard'!A2:G8");
});

test("broker write receipts open the actual Google Sheets screen and saved worksheet", () => {
  for (const operation of ["google-sheets.add-multiple-rows", "google-sheets.update-row", "google-sheets.update-multiple-rows"]) {
    const output = brokerWrite(operation);
    const before = structuredClone(output);
    const result = primaryResultFromOutputs([output], { title: "Draft the content" });
    assert.equal(result.kind, "spreadsheet");
    assert.equal(result.title, "Dashboard");
    assert.equal(result.range, "Dashboard!A1:G8");
    assert.equal(result.sourceOperation, operation);
    assert.equal(result.spreadsheetId, "broker-workbook");
    const link = new URL(result.link);
    assert.equal(link.origin, "https://docs.google.com");
    assert.equal(link.pathname, "/spreadsheets/d/broker-workbook/edit");
    assert.equal(new URLSearchParams(link.hash.slice(1)).get("gid"), "173");
    assert.equal(new URLSearchParams(link.hash.slice(1)).get("range"), "A1:G8");
    assert.equal(new URL(result.embedUrl).searchParams.get("rm"), "minimal");
    assert.deepEqual(result.ranges, []);
    assert.equal(result.verified, false);
    assert.doesNotMatch(JSON.stringify(result), /Requested cells are not readback/);
    assert.deepEqual(output, before);
  }
});

test("checkpoint previews retain the persisted operation when the output envelope omits it", () => {
  const { operation, ...output } = brokerWrite();
  const step = { id: "save-step", key: "save", tool: "google-sheets", status: "completed", operation, output };
  const entries = toolResultEntries([step]);
  assert.equal(entries[0].preview.kind, "spreadsheet");
  assert.equal(entries[0].preview.sourceStepId, "save-step");
  assert.equal(toolOutputResult(entries, [step]).kind, "spreadsheet");
});

test("broker previews reject failed receipts and never invent a tab or claim requested values were read back", () => {
  const output = brokerWrite();
  for (const error of [{ error: "Failed" }, { isError: true }, { is_error: true }, { success: false }]) {
    assert.equal(googleSheetsResult([{ ...output, provider_result: { ...output.provider_result, ...error } }]), null);
    assert.equal(googleSheetsResult([{ ...output, provider_result: { ret: { ...output.provider_result.ret, ...error } } }]), null);
  }
  for (const id of ["../bad", "javascript:alert(1)", "bad?token=secret"]) {
    assert.equal(googleSheetsResult([{ ...output, provider_result: { ret: { spreadsheetId: id } } }]), null);
  }
  for (const worksheetId of [undefined, -1, true, "not-a-tab"]) {
    const result = googleSheetsResult([{ ...output, resolved_arguments: { ...output.resolved_arguments, worksheetId } }]);
    assert.equal(new URLSearchParams(new URL(result.link).hash.slice(1)).has("gid"), false);
    assert.deepEqual(result.ranges, []);
  }
  const observed = { ret: { range: "Dashboard!A1:G8", values: [["Actual saved value"]] } };
  assert.deepEqual(googleSheetsResult([{ ...output, outcome_check: { status: "verified", observed } }]).ranges[0].values,
    [["Actual saved value"]]);
});

test("broker workbook creations keep their provider title and never invent cell contents", () => {
  const result = googleSheetsResult([{ step_key: "create", operation: "google-sheets.new-spreadsheet",
    provider_result: { ret: { spreadsheetId: "new-workbook", title: "September KPI dashboard", worksheetName: "Dashboard" } } }]);
  assert.equal(result.kind, "spreadsheet");
  assert.equal(result.title, "September KPI dashboard");
  assert.equal(result.spreadsheetId, "new-workbook");
  assert.deepEqual(result.ranges, []);
});


test("a partial read of the written range remains visible without claiming a complete preview", () => {
  const read = brokerRead();
  read.resolved_arguments.range = "A1:F200";
  const result = googleSheetsResult([brokerWrite(), read]);
  assert.equal(result.readBack, true);
  assert.equal(result.partialReadBack, true);
  assert.equal(result.range, "Dashboard!A1:G8");
  assert.equal(result.ranges[0].range, "'Dashboard'!A1:F200");
  assert.deepEqual(result.ranges[0].values, read.provider_result.ret.rows);
});
