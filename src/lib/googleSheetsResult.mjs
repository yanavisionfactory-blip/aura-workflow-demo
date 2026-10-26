const WRITES = new Set(["sheets.append", "sheets.kpi.create", "sheets.campaign_report.create"]);
const READS = new Set(["sheets.read", "sheets.workbook.get", "sheets.campaign_report.get"]);
const validId = (id) => typeof id === "string" && /^[A-Za-z0-9_-]+$/.test(id);
const resultOf = (output) => output?.provider_result || {};

export function spreadsheetId(output) {
  const result = resultOf(output);
  const id = result.spreadsheetId || output?.resolved_arguments?.spreadsheet_id;
  if (validId(id)) return id;
  try {
    const url = new URL(result.spreadsheetUrl || result.result_url);
    if (url.protocol !== "https:" || url.hostname !== "docs.google.com") return null;
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

function grids(receipt) {
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

export function googleSheetsResult(outputs, context = {}, explicitPrimary = null) {
  const sheets = outputs.filter((output) => (WRITES.has(output.operation) || READS.has(output.operation))
    && !resultOf(output).error && !resultOf(output).isError && spreadsheetId(output)
    && (!WRITES.has(output.operation) || validId(resultOf(output).spreadsheetId)));
  if (!sheets.length || (explicitPrimary && !sheets.includes(explicitPrimary))) return null;
  const targetId = explicitPrimary && spreadsheetId(explicitPrimary);
  const matching = sheets.filter((output) => !targetId || spreadsheetId(output) === targetId);
  const write = [...matching].reverse().find((output) => WRITES.has(output.operation));
  if (!explicitPrimary && !write && outputs.some((output) => !sheets.includes(output))) return null;
  const id = spreadsheetId(write || explicitPrimary || matching.at(-1));
  const targetRange = resultOf(write).updates?.updatedRange;
  const read = [...matching].reverse().find((output) => READS.has(output.operation)
    && spreadsheetId(output) === id && (!targetRange || resultOf(output).range === targetRange));
  const checked = write?.outcome_check?.status === "verified";
  // Display actual provider reads, never the requested write values as proof.
  const receipt = read ? resultOf(read) : checked ? write.outcome_check.observed || {} : {};
  const ranges = grids(receipt);
  const range = targetRange || ranges[0]?.range || resultOf(explicitPrimary).range || "";
  const origin = sheetRange(range);
  const headerRead = matching.find((output) => {
    const item = resultOf(output), at = sheetRange(item.range);
    return READS.has(output.operation) && spreadsheetId(output) === id && at?.tab === origin?.tab
      && at?.column === origin?.column && at?.row === 1 && item.values?.length === 1
      && /\$?[A-Z]+\$?1(?::\$?[A-Z]+\$?1)?$/i.test(item.range || "");
  });
  const headers = headerRead ? resultOf(headerRead).values[0] : [];
  const gid = ranges[0]?.gid;
  return { kind: "spreadsheet", provider: "Google Sheets", providerVerb: write ? checked ? "Saved and verified in" : "Saved in" : "Read from",
    title: resultOf(write).properties?.title || resultOf(read).properties?.title || context.title || "Google Sheets result",
    sourceStepKey: read?.step_key || write?.step_key || explicitPrimary?.step_key,
    sourceStepId: read?.step_id || write?.step_id || explicitPrimary?.step_id,
    spreadsheetId: id, range, ranges, headers, sheetId: gid, verified: Boolean(checked),
    ...sheetAppLinks(id, range, gid), linkLabel: "Open in Google Sheets", downloadUrl: null };
}
