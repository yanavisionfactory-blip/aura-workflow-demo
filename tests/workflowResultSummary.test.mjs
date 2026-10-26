import test from "node:test";
import assert from "node:assert/strict";
import { sheetWorkflowSummary } from "../src/lib/workflowResultSummary.mjs";

const primary = { kind: "spreadsheet", spreadsheetId: "pilot", verified: true };
const read = (tab, id = tab) => ({ id, operation: "sheets.read", status: "completed", hasResponse: true,
  inputs: { spreadsheet_id: "pilot" }, response: { range: `'${tab}'!A1:B10`, values: [["Saved input"]] } });
const compose = { id: "compose", operation: "report.compose", status: "completed", hasResponse: true, response: { body: "Saved report" } };
const write = { id: "append", operation: "sheets.append", status: "completed", hasResponse: true,
  response: { spreadsheetId: "pilot", updates: { updatedRange: "'Pilot Record'!A49:B52", updatedRows: 4 } },
  inputs: { values: Array(500).fill(["Planned rows are not proof"]) } };

test("Sheet overview counts actual source tabs, report and saved rows without counting verification as a source", () => {
  const summary = sheetWorkflowSummary([read("Competitor Comparison"), read("KPI Dashboard"), read("Pilot Record"), compose, write, read("Pilot Record", "verify")], primary);
  assert.deepEqual(summary.metrics, [{ value: 3, label: "source tabs read" }, { value: 1, label: "report prepared" }, { value: 4, label: "rows saved" }]);
  assert.equal(summary.title, "Report saved to Google Sheets");
  assert.match(summary.summary, /read back and verified/);
  assert.equal(summary.actions[1].title, "report prepared with ChatGPT");
  assert.equal(summary.actions[2].detail, "Pilot Record · Saved cells verified");
});

test("source tabs deduplicate repeated reads while preserving separate workbooks", () => {
  const other = { ...read("KPI Dashboard", "other"), inputs: { spreadsheet_id: "other" } };
  const summary = sheetWorkflowSummary([read("KPI Dashboard"), read("KPI Dashboard", "again"), other, write], primary);
  assert.equal(summary.metrics[0].value, 2);
});

test("provider updated range supplies a saved row count when explicit row count is absent", () => {
  const summary = sheetWorkflowSummary([{ ...write, response: { spreadsheetId: "pilot", updates: { updatedRange: "'Pilot Record'!A49:B52" } } }], primary);
  assert.deepEqual(summary.metrics, [{ value: 4, label: "rows saved" }]);
});

test("failed writes, failed reports and planned values never become success metrics", () => {
  const summary = sheetWorkflowSummary([read("Source"), { ...compose, status: "provider_error" }, { ...write, status: "failed" }], primary);
  assert.deepEqual(summary.metrics, [{ value: 1, label: "source tab read" }]);
  assert.equal(summary.title, undefined);
  assert.equal(summary.actions.length, 1);
});

test("an unverified write with no row receipt does not invent a count or verification", () => {
  const summary = sheetWorkflowSummary([{ ...write, response: { spreadsheetId: "pilot" } }], { ...primary, verified: false });
  assert.deepEqual(summary.metrics, []);
  assert.equal(summary.actions[0].count, undefined);
  assert.equal(summary.actions[0].detail, "Write receipt saved");
  assert.doesNotMatch(summary.summary, /verified/);
});

test("non-Sheets results keep their own presentation", () => {
  assert.equal(sheetWorkflowSummary([compose], { kind: "document" }), null);
});
