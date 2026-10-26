import { sheetRange } from "./googleSheetsResult.mjs";

const writes = new Set(["sheets.append", "sheets.kpi.create", "sheets.campaign_report.create"]);
const reads = new Set(["sheets.read", "sheets.workbook.get", "sheets.campaign_report.get"]);
const completed = (entry) => entry.status === "completed" && entry.hasResponse;
const plural = (count, singular, multiple = `${singular}s`) => count === 1 ? singular : multiple;

// Summarize saved provider receipts, never planned arguments or sample metrics.
export function sheetWorkflowSummary(entries, primary) {
  if (primary.kind !== "spreadsheet") return null;
  const matchingWrites = entries.filter((entry) => completed(entry) && writes.has(entry.operation)
    && entry.response?.spreadsheetId === primary.spreadsheetId);
  const write = matchingWrites.at(-1);
  const firstWrite = entries.findIndex((entry) => writes.has(entry.operation));
  const firstReport = entries.findIndex((entry) => completed(entry) && entry.operation === "report.compose");
  const preceding = entries.slice(0, firstReport >= 0 ? firstReport : firstWrite < 0 ? entries.length : firstWrite);
  const pages = [...new Map(preceding.filter((entry) => completed(entry) && entry.operation === "web.page.read")
    .map((entry) => [entry.response?.url || entry.inputs?.url || entry.id, entry])).values()];
  const sourceEntries = preceding
    .filter((entry) => completed(entry) && reads.has(entry.operation));
  const tabs = [...new Map(sourceEntries.flatMap((entry) => {
    const tab = sheetRange(entry.response?.range)?.tab;
    if (!tab) return [];
    const id = entry.response?.spreadsheetId || entry.inputs?.spreadsheet_id || entry.id;
    return [[`${id}:${tab}`, { tab, entry }]];
  })).values()];
  const reports = entries.filter((entry) => completed(entry) && entry.operation === "report.compose"
    && typeof entry.response?.body === "string" && entry.response.body.trim());
  const updated = write?.response?.updates;
  const coordinates = updated?.updatedRange?.split("!").at(-1).match(/^\$?[A-Z]+\$?(\d+)(?::\$?[A-Z]+\$?(\d+))?$/i);
  const rows = Number.isInteger(updated?.updatedRows) && updated.updatedRows >= 0 ? updated.updatedRows
    : coordinates ? Number(coordinates[2] || coordinates[1]) - Number(coordinates[1]) + 1 : null;
  const metrics = [], actions = [];
  if (pages.length) {
    metrics.push({ value: pages.length, label: `${plural(pages.length, "web page")} read` });
    actions.push({ key: "web-sources", count: pages.length, title: `${plural(pages.length, "public web page")} researched`,
      detail: "Public website pages retrieved before the report.", icon: "sources", actionId: pages[0].id, actionLabel: "View sources" });
  }
  if (tabs.length) {
    metrics.push({ value: tabs.length, label: `${plural(tabs.length, "source tab")} read` });
    actions.push({ key: "sheet-sources", count: tabs.length, title: `${plural(tabs.length, "source tab")} read in Google Sheets`,
      detail: tabs.map(({ tab }) => tab).join(" · "), icon: "sources", actionId: tabs[0].entry.id, actionLabel: "View sources" });
  }
  if (reports.length) {
    metrics.push({ value: reports.length, label: `${plural(reports.length, "report")} prepared` });
    actions.push({ key: "chatgpt-reports", count: reports.length, title: `${plural(reports.length, "report")} prepared with ChatGPT`,
      detail: "Prepared from the workflow’s saved source inputs.", icon: "report", actionId: reports.at(-1).id, actionLabel: "View report" });
  }
  if (write) {
    if (rows !== null) metrics.push({ value: rows, label: `${plural(rows, "row")} saved` });
    actions.push({ key: "sheet-output", count: rows ?? undefined, title: rows === null ? "Saved to Google Sheets" : `${plural(rows, "row")} saved to Google Sheets`,
      detail: [sheetRange(updated?.updatedRange)?.tab, primary.verified ? "Saved cells verified" : "Write receipt saved"].filter(Boolean).join(" · "),
      icon: "sheet", actionId: "main", actionLabel: "View result" });
  }
  const sources = [pages.length ? `${pages.length} ${plural(pages.length, "public web page")}` : "",
    tabs.length ? `${tabs.length} ${plural(tabs.length, "source tab")}` : ""].filter(Boolean).join(" and ");
  return { metrics, actions,
    title: write ? reports.length ? "Report saved to Google Sheets" : "Results saved to Google Sheets" : undefined,
    summary: write ? `${reports.length ? "ChatGPT prepared the report" : "The workflow saved its results"}${sources ? ` using ${sources}` : ""}. ${primary.verified ? "The saved Google Sheets cells were read back and verified." : "Open the result below to review the saved output."}` : undefined };
}
