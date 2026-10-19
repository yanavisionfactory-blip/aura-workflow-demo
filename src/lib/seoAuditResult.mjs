import { toolEvidence } from "./toolEvidence.mjs";

const uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const runLinks = (text = "") => [...String(text).matchAll(new RegExp(`https://[^\\s<>]+/runs/(${uuid})(?=[\\s.,;)\\]]|$)`, "gi"))].map((match) => match[1]);
const groups = ["Technical SEO", "Content", "Internal linking", "Backlinks"];

// A typed source packet, not keywords in a report body, opts into this view.
// References are UUIDs only: reads always use the existing tenant-scoped API.
export function seoAuditManifest(sources = []) {
  const byId = Object.fromEntries(sources.map((source) => [source.id, source]));
  if (!["CRAWL", "BACKLOG", "TOOLS", "INTAKE"].every((id) => typeof byId[id]?.content === "string")) return null;
  let table;
  try { table = JSON.parse(byId.BACKLOG.content); } catch { return null; }
  const required = ["id", "priority", "group", "title", "affected_csv_rows", "evidence", "fix", "effort", "dependencies", "reasoning", "expert_review", "acceptance"];
  if (!Array.isArray(table.columns) || !required.every((key) => table.columns.includes(key))
    || !Array.isArray(table.rows) || !table.rows.length || table.rows.length > 200) return null;
  if (!table.rows.every((row) => Array.isArray(row) && row.length === table.columns.length)) return null;
  const backlog = table.rows.map((row) => Object.fromEntries(table.columns.map((key, index) => [key, row[index]])));
  if (!backlog.every((item) => typeof item.id === "string" && typeof item.title === "string"
    && ["P1", "P2", "P3"].includes(item.priority)
    && required.filter((key) => key !== "affected_csv_rows").every((key) => typeof item[key] === "string")
    && (item.kind === undefined || typeof item.kind === "string")
    && groups.some((group) => group.toLowerCase() === String(item.group).toLowerCase())
    && Array.isArray(item.affected_csv_rows) && item.affected_csv_rows.every((row) => Number.isInteger(row) && row >= 2))) return null;
  const crawlRunId = runLinks(byId.CRAWL.content)[0];
  if (!crawlRunId) return null;
  const toolsText = byId.TOOLS.content;
  const segment = (name) => toolsText.match(new RegExp(`${name}:([\\s\\S]*?)(?=(?:Semrush|Ahrefs|Sitebulb|Screaming Frog):|$)`, "i"))?.[1]?.trim() || "";
  return {
    backlog,
    references: [
      { key: "crawl", name: "Screaming Frog", runId: crawlRunId },
      ...["Semrush", "Ahrefs"].map((name) => ({ key: name.toLowerCase(), name, runId: runLinks(segment(name))[0] || null })),
    ],
    sourceNotes: { crawl: byId.CRAWL.content, intake: byId.INTAKE.content, sitebulb: segment("Sitebulb") },
  };
}

export function runEvidence(run, name) {
  return toolEvidence((run?.steps || []).map((step) => ({
    ...step, stepKey: step.key, tool: name, action: step.reason || step.operation,
    arguments: step.arguments, output: step.output,
  })));
}

export function crawlResult(run) {
  return (run?.steps || []).find((step) => (step.output?.operation || step.operation) === "seo.crawl.analyze"
    && step.output?.provider_result?.source_tool === "Screaming Frog")?.output.provider_result || null;
}

export function providerOutcome(run, name) {
  const actions = runEvidence(run, name);
  const failed = actions.find((action) => action.status === "provider_error");
  const response = failed?.response;
  const mcpError = response?.content?.find((part) => part && typeof part === "object" && part.code);
  const error = response?.error;
  if (failed) return {
    state: "blocked", label: "Access blocked", code: String(mcpError?.code || error?.response?.status || error?.status || "Provider error"),
    message: String(mcpError?.message || error?.response?.data?.error || error?.message || "The provider returned an error."), actions,
  };
  const hasData = actions.some((action) => action.hasResponse && action.status === "completed");
  return { state: hasData ? "returned" : "unavailable", label: hasData ? "Response saved" : "No research output", code: "", message: hasData ? "Inspect the saved response below." : "No usable research response is saved for this source.", actions };
}

// This deliberately excludes inferred vendor URLs, account-access links and
// links buried in debug text. Only explicit provider result fields are offered.
export function providerResultLink(run) {
  for (const step of run?.steps || []) {
    const response = step.output?.provider_result;
    if (!response || response.is_error || response.isError || response.error) continue;
    const candidate = response.report_url || response.result_url || response.dashboard_url;
    if (typeof candidate !== "string") continue;
    try {
      const url = new URL(candidate);
      if (url.protocol === "https:" && !url.username && !url.password
        && ![...url.searchParams.keys()].some((key) => /key|token|secret|auth|signature/i.test(key))) return url.href;
    } catch { /* An absent or unsafe result URL stays unavailable. */ }
  }
  return null;
}

export function parseCsv(text) {
  const rows = []; let row = []; let field = ""; let quoted = false;
  const input = String(text).replace(/^\uFEFF/, "");
  for (let i = 0; i < input.length; i++) {
    const char = input[i];
    if (char === '"') {
      if (quoted && input[i + 1] === '"') { field += '"'; i++; }
      else quoted = !quoted;
    } else if (char === "," && !quoted) { row.push(field); field = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      row.push(field); rows.push(row); row = []; field = "";
      if (char === "\r" && input[i + 1] === "\n") i++;
    } else field += char;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  return rows;
}

export function crawlInventory(run, decodeBase64) {
  const documents = run?.inputs?.attached_documents || run?.inputs?.documents || [];
  for (const doc of documents) {
    if (typeof doc.file_url !== "string" || !doc.file_url.startsWith("data:")) continue;
    try {
      const comma = doc.file_url.indexOf(",");
      const metadata = doc.file_url.slice(0, comma);
      const data = doc.file_url.slice(comma + 1);
      const text = metadata.includes(";base64") ? decodeBase64(data) : decodeURIComponent(data);
      const [headers, ...rows] = parseCsv(text);
      // The full Internal inventory is recognized by columns, never a filename.
      if (!headers?.includes("Address") || !headers.includes("Canonical Link Element 1")) continue;
      return rows.filter((row) => row.some(Boolean)).map((row, index) => ({
        ...Object.fromEntries(headers.map((header, col) => [header, row[col] || ""])), csv_row: index + 2,
      }));
    } catch { /* Leave row mappings unresolved if an attachment cannot decode. */ }
  }
  return [];
}

export function mappedBacklog(backlog, inventory) {
  const byRow = new Map(inventory.map((row) => [row.csv_row, row]));
  return [...backlog].sort((a, b) => a.priority.localeCompare(b.priority)).map((item) => ({ ...item, affected: item.affected_csv_rows.map((number) => {
    const row = byRow.get(number);
    return { csv_row: number, url: row?.Address || "", status: row?.["Status Code"] || "", canonical: row?.["Canonical Link Element 1"] || "" };
  }) }));
}

export const seoAuditGroups = groups;
