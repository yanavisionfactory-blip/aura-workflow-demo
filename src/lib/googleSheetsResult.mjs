const WRITES = new Set(["sheets.append", "sheets.kpi.create", "sheets.campaign_report.create"]);
const READS = new Set(["sheets.read", "sheets.workbook.get", "sheets.campaign_report.get"]);
const validId = (id) => typeof id === "string" && /^[A-Za-z0-9_-]+$/.test(id);
const brokerOperation = (operation = "") => operation.startsWith("google-sheets.");
export const isSheetsWrite = (operation = "") => WRITES.has(operation)
  || /^google-sheets\.(?:new|create|add|append|update|format|clear)-/.test(operation);
export const isSheetsRead = (operation = "") => READS.has(operation)
  || /^google-sheets\.(?:get|list|read|find|search)-/.test(operation);
export const sheetReceipt = (output) => {
  const receipt = output?.provider_result || {};
  return receipt.ret && typeof receipt.ret === "object" && !Array.isArray(receipt.ret) ? receipt.ret : receipt;
};
const isWrite = isSheetsWrite, isRead = isSheetsRead, resultOf = sheetReceipt;
const failed = (output) => [output?.provider_result, resultOf(output)]
  .some((receipt) => receipt?.error || receipt?.isError || receipt?.is_error || receipt?.success === false);
const writtenRange = (output) => resultOf(output).updates?.updatedRange || resultOf(output).updatedRange;
const tabId = (value) => {
  const number = typeof value === "string" && /^\d+$/.test(value) ? Number(value) : value;
  return Number.isInteger(number) && number >= 0 && number <= 2147483647 ? number : undefined;
};

export function spreadsheetId(output) {
  const result = resultOf(output);
  const args = output?.resolved_arguments || {};
  const id = result.spreadsheetId || args.spreadsheet_id || args.spreadsheetId
    || (brokerOperation(output?.operation) ? args.sheetId : null);
  if (validId(id)) return id;
  try {
    const url = new URL(result.spreadsheetUrl || result.result_url);
    if (url.protocol !== "https:" || url.hostname !== "docs.google.com" || url.username || url.password) return null;
    return url.pathname.match(/^\/spreadsheets\/d\/([A-Za-z0-9_-]+)\/(?:edit|preview)\/?$/)?.[1] || null;
  } catch { return null; }
}

export function sheetRange(range = "") {
  const match = String(range).match(/^(?:(?:'((?:[^']|'')+)'|([^!]+))!)?\$?([A-Z]+)\$?(\d+)(?::\$?[A-Z]+\$?\d+)?$/i);
  if (!match) return null;
  return { tab: (match[1] || match[2] || "").replaceAll("''", "'"),
    row: Number(match[4]), column: match[3].toUpperCase().split("").reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0) - 1 };
}

export function columnName(index) {
  let value = index + 1, label = "";
  while (value > 0) { value--; label = String.fromCharCode(65 + value % 26) + label; value = Math.floor(value / 26); }
  return label;
}

export function sheetAppLinks(id, range, gid) {
  const link = new URL(`https://docs.google.com/spreadsheets/d/${id}/edit`);
  const fragment = new URLSearchParams();
  if (Number.isInteger(gid) && gid >= 0) {
    fragment.set("gid", String(gid));
    if (sheetRange(range)) fragment.set("range", range.split("!").at(-1));
  }
  link.hash = fragment.toString();
  const embed = new URL(link); embed.searchParams.set("rm", "minimal");
  return { link: link.toString(), embedUrl: embed.toString() };
}

function grids(receipt, output) {
  // The broker's read-rows action returns evaluated cell arrays in ret.rows,
  // without an A1 range. Use only that read's resolved destination, never a
  // report's proposed rows or a write's requested values.
  if (output?.operation === "google-sheets.read-rows") {
    const args = output.resolved_arguments || {};
    const origin = sheetRange(args.range);
    const name = origin?.tab || args.sheetName;
    if (args.hasHeaders !== false || !origin || !name
        || (origin.tab && args.sheetName && origin.tab !== args.sheetName)
        || !Array.isArray(receipt.rows) || !receipt.rows.every((row) => Array.isArray(row)
          && row.every((cell) => cell === null || ["string", "number", "boolean"].includes(typeof cell)))) return [];
    const range = `'${String(name).replaceAll("'", "''")}'!${args.range.split("!").at(-1)}`;
    return [{ range, values: receipt.rows }];
  }
  if (Array.isArray(receipt.values) && sheetRange(receipt.range)) {
    return [{ range: receipt.range, values: receipt.majorDimension === "COLUMNS"
      ? Array.from({ length: Math.max(0, ...receipt.values.map((column) => column.length)) }, (_, row) => receipt.values.map((column) => column[row] ?? ""))
      : receipt.values }];
  }
  return (receipt.sheets || []).flatMap((sheet) => (sheet.data || []).map((block) => {
    const values = (block.rowData || []).map((row) => (row.values || []).map((cell) => cell.formattedValue
      ?? cell.effectiveValue?.stringValue ?? cell.effectiveValue?.numberValue ?? cell.effectiveValue?.boolValue ?? ""));
    if (!values.length) return null;
    return { range: `'${String(sheet.properties?.title || "Sheet").replaceAll("'", "''")}'!${columnName(block.startColumn || 0)}${(block.startRow || 0) + 1}`,
      values, gid: sheet.properties?.sheetId };
  }).filter(Boolean));
}

function matchesRange(grid, target, allowPartial = false) {
  const source = sheetRange(grid.range), destination = sheetRange(target);
  if (!source || !destination || source.tab !== destination.tab) return false;
  const end = (range, origin, values = []) => {
    const last = range.split("!").at(-1).split(":")[1];
    return last ? sheetRange(last) : { row: origin.row + Math.max(1, values.length) - 1,
      column: origin.column + Math.max(1, ...values.map((row) => row.length)) - 1 };
  };
  const lastSource = end(grid.range, source, grid.values), lastTarget = end(target, destination);
  if (!lastSource || !lastTarget) return false;
  if (allowPartial) return source.row <= lastTarget.row && source.column <= lastTarget.column
    && lastSource.row >= destination.row && lastSource.column >= destination.column;
  return source.row <= destination.row && source.column <= destination.column
    && lastSource.row >= lastTarget.row && lastSource.column >= lastTarget.column;
}

export function googleSheetsResult(outputs, context = {}, explicitPrimary = null) {
  const sheets = outputs.filter((output) => (isWrite(output.operation) || isRead(output.operation))
    && !failed(output) && spreadsheetId(output)
    && (!isWrite(output.operation) || validId(resultOf(output).spreadsheetId)));
  if (!sheets.length || (explicitPrimary && !sheets.includes(explicitPrimary))) return null;
  const targetId = explicitPrimary && spreadsheetId(explicitPrimary);
  const matching = sheets.filter((output) => !targetId || spreadsheetId(output) === targetId);
  const write = [...matching].reverse().find((output) => isWrite(output.operation));
  if (!explicitPrimary && !write && outputs.some((output) => !sheets.includes(output))) return null;
  const id = spreadsheetId(write || explicitPrimary || matching.at(-1));
  const targetRange = writtenRange(write);
  const read = [...matching].reverse().find((output) => isRead(output.operation)
    && spreadsheetId(output) === id && (!write || matching.indexOf(output) > matching.indexOf(write))
    && (!targetRange || grids(resultOf(output), output).some((grid) => matchesRange(grid, targetRange, true))));
  const checked = write?.outcome_check?.status === "verified";
  // Display actual provider reads, never the requested write values as proof.
  const receipt = read ? resultOf(read) : checked ? resultOf({ provider_result: write.outcome_check.observed }) : {};
  const ranges = grids(receipt, read);
  const range = targetRange || ranges[0]?.range || resultOf(explicitPrimary).range || "";
  const origin = sheetRange(range);
  const headerRead = matching.find((output) => {
    const item = resultOf(output), at = sheetRange(item.range);
    return isRead(output.operation) && spreadsheetId(output) === id && at?.tab === origin?.tab
      && at?.column === origin?.column && at?.row === 1 && item.values?.length === 1
      && /\$?[A-Z]+\$?1(?::\$?[A-Z]+\$?1)?$/i.test(item.range || "");
  });
  const headers = headerRead ? resultOf(headerRead).values[0] : [];
  const source = read || write || explicitPrimary || matching.at(-1);
  const gid = tabId(ranges[0]?.gid) ?? (brokerOperation(write?.operation)
    ? tabId(write?.resolved_arguments?.worksheetId) : undefined);
  const named = matching.find((output) => spreadsheetId(output) === id
    && (resultOf(output).properties?.title || resultOf(output).title));
  return { kind: "spreadsheet", provider: "Google Sheets", providerVerb: write ? checked ? "Saved and verified in" : "Saved in" : "Read from",
    title: resultOf(named).properties?.title || resultOf(named).title || origin?.tab || context.title || "Google Sheets result",
    sourceStepKey: source?.step_key, sourceStepId: source?.step_id, sourceOperation: source?.operation,
    spreadsheetId: id, range, ranges, headers, sheetId: gid, verified: Boolean(checked), readBack: Boolean(read && ranges.length),
    partialReadBack: Boolean(read && targetRange && !ranges.some((grid) => matchesRange(grid, targetRange))),
    ...sheetAppLinks(id, range, gid), linkLabel: "Open in Google Sheets", downloadUrl: null };
}
