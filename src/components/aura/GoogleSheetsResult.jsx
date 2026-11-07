import { useEffect, useState } from "react";
import { ArrowUpRight, CheckCircle2, Table2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { documentMarkdownOptions } from "@/lib/documentMarkdown.mjs";
import { columnName, sheetAppLinks, sheetRange } from "@/lib/googleSheetsResult.mjs";
import { auraRequest } from "@/lib/auraApi";
import { sheetComparisonMarkdown } from "@/lib/sheetReviewEdit.mjs";
import { downloadTextFile } from "@/lib/auraDownload";

function MobileReportRows({ grid }) {
  const headers = grid.values[0].map(String);
  const metrics = /^(Spend|Impressions|Clicks|CTR|CPC|Conversions|CPA|Conversion ?Value|ROAS)$/i;
  const rows = grid.values.slice(1);
  const isData = (row) => headers.some((label, index) => metrics.test(label) && row[index] !== undefined && row[index] !== "");
  const notes = rows.filter((row) => !isData(row) && row.some((value) => value !== ""));
  return <div className="space-y-4 p-4 sm:hidden" aria-label="Campaign report cards">{rows.filter(isData).map((row, index) => {
    const values = headers.map((label, column) => ({ label, value: String(row[column] ?? "") }));
    const measured = values.filter(({ label }) => metrics.test(label));
    const unavailable = measured.length > 0 && measured.every(({ value }) => !value || /^unavailable$/i.test(value));
    const context = values.filter(({ label, value }, i) => i > 0 && !metrics.test(label) && value && !/chart$/i.test(label));
    return <article key={index} className="rounded-xl border border-slate-200 p-4"><h4 className="font-semibold">{row[0]}</h4>
      {unavailable ? <p className="mt-3 text-sm text-slate-600">Metrics unavailable. See the reporting context below.</p> : <dl className="mt-4 grid grid-cols-2 gap-4">{measured.map(({ label, value }) => <div key={label}><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm font-semibold tabular-nums">{value || "Unavailable"}</dd></div>)}</dl>}
      {context.length > 0 && <details className="mt-4 border-t border-slate-200 pt-3"><summary className="cursor-pointer text-xs font-medium text-emerald-800">Reporting context</summary><dl className="mt-3 space-y-3">{context.map(({ label, value }) => <div key={label}><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words text-xs leading-5">{value}</dd></div>)}</dl></details>}
    </article>;
  })}{notes.length > 0 && <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-medium text-emerald-800">Reporting notes</summary><dl className="mt-3 space-y-4">{notes.map((row, index) => <div key={index}><dt className="text-xs font-medium">{row[0]}</dt><dd className="mt-1 text-xs leading-5 text-slate-600">{row.slice(1).filter(Boolean).join(" · ")}</dd></div>)}</dl></details>}</div>;
}

function SavedCells({ ranges = [], initialRange }) {
  const [tab, setTab] = useState(() => Math.max(0, ranges.findIndex((grid) => sheetRange(grid.range)?.tab === sheetRange(initialRange)?.tab)));
  const grid = ranges[tab];
  const [selected, setSelected] = useState(null);
  if (!grid) return <p className="p-6 text-sm text-slate-600">No saved cell data is available for this workbook. Open Google Sheets to inspect the actual result.</p>;
  const origin = sheetRange(grid.range);
  const reportCards = origin?.row === 1 && /^platform$/i.test(String(grid.values[0]?.[0]));
  const columns = Math.max(1, ...grid.values.map((row) => row.length));
  const longCells = grid.values.flatMap((row, r) => row.map((value, c) => ({ r, c, value })))
    .filter((cell) => typeof cell.value === "string" && cell.value.length > 200).sort((a, b) => b.value.length - a.value.length);
  const active = selected || longCells[0];
  const address = (r, c) => `${columnName(origin.column + c)}${origin.row + r}`;
  return <div className="bg-white text-slate-800">
    <div className="flex flex-wrap gap-1 border-b border-slate-200 bg-[#f8fafd] px-3 pt-2" role="tablist" aria-label="Saved sheet ranges">
      {ranges.map((item, index) => <button type="button" role="tab" aria-selected={index === tab} key={`${item.range}-${index}`} onClick={() => { setTab(index); setSelected(null); }} className={`rounded-t-lg px-4 py-2.5 text-xs font-medium ${index === tab ? "border-b-2 border-emerald-700 bg-emerald-50 text-emerald-800" : "text-slate-600"}`}>{sheetRange(item.range)?.tab || item.range}{ranges.filter((grid) => sheetRange(grid.range)?.tab === sheetRange(item.range)?.tab).length > 1 ? ` · ${item.range.split("!").at(-1)}` : ""}</button>)}
    </div>
    {reportCards && <MobileReportRows grid={grid} />}
    <div className={`max-h-80 overflow-auto ${reportCards ? "hidden sm:block" : ""}`} aria-label="Saved Google Sheets cells">
      <table className="w-full border-collapse text-left text-xs"><thead className="sticky top-0 z-10 bg-[#f1f3f4] text-slate-600"><tr><th className="w-12 border border-slate-200" />{Array.from({ length: columns }, (_, c) => <th key={c} className="border border-slate-200 px-3 py-2 text-center font-normal">{columnName(origin.column + c)}</th>)}</tr></thead>
        <tbody>{grid.values.map((row, r) => <tr key={r}><th className="w-12 border border-slate-200 bg-[#f1f3f4] px-3 py-2 text-center font-normal text-slate-500">{origin.row + r}</th>{Array.from({ length: columns }, (_, c) => <td key={c} className={`min-w-36 max-w-xl border border-slate-200 align-top ${active?.r === r && active?.c === c ? "bg-blue-50 outline outline-2 -outline-offset-2 outline-blue-500" : ""}`}>
          <button type="button" aria-label={`Cell ${address(r, c)}`} onClick={() => setSelected({ r, c, value: row[c] ?? "" })} className="block w-full px-3 py-2 text-left"><span className="line-clamp-3 whitespace-pre-wrap break-words">{String(row[c] ?? "") || "\u00a0"}</span></button>
        </td>)}</tr>)}</tbody>
      </table>
    </div>
    {active && <section aria-label="Selected cell contents" className={`border-t border-slate-200 ${reportCards ? "hidden sm:block" : ""}`}>
      <div className="flex items-center gap-3 bg-[#f8fafd] px-4 py-2 text-xs"><span className="rounded border border-slate-200 bg-white px-2 py-1 font-medium">{address(active.r, active.c)}</span><span className="text-slate-600">Complete saved cell</span></div>
      <div className="max-h-[32rem] overflow-auto p-5 text-sm leading-7 [text-wrap:pretty] [&_h1]:mb-4 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-6 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-4 [&_h3]:font-semibold [&_p]:mb-3 [&_table]:block [&_table]:overflow-auto [&_th]:border [&_th]:border-slate-200 [&_th]:bg-slate-50 [&_th]:p-2 [&_td]:min-w-40 [&_td]:border [&_td]:border-slate-200 [&_td]:p-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_a]:text-blue-700 [&_a]:underline">
        <ReactMarkdown {...documentMarkdownOptions}>{String(active.value ?? "")}</ReactMarkdown>
      </div>
    </section>}
  </div>;
}

export default function GoogleSheetsResult({ result, backendRunId }) {
  // Saved results must remain visible even when Google's embedded session
  // requires a separate sign-in or third-party-cookie decision.
  const hasSavedCells = Boolean(result.ranges?.some((grid) => grid.values?.length));
  const [view, setView] = useState("saved");
  useEffect(() => { setView("saved"); }, [result.spreadsheetId, hasSavedCells]);
  const resolveTab = Boolean(backendRunId && result.sourceStepKey && !Number.isInteger(result.sheetId)
    && !result.sourceOperation?.startsWith("google-sheets."));
  const [screen, setScreen] = useState(null);
  const [loading, setLoading] = useState(resolveTab);
  useEffect(() => {
    if (!resolveTab) return;
    let active = true;
    setLoading(true);
    auraRequest(`/v1/runs/${encodeURIComponent(backendRunId)}/steps/${encodeURIComponent(result.sourceStepKey)}/sheet-screen`, { timeoutMs: 20000 })
      .then((data) => {
        if (!active) return;
        if (data.spreadsheetId !== result.spreadsheetId || !Number.isInteger(data.sheetId) || data.sheetId < 0) throw new Error("Unmatched spreadsheet tab");
        setScreen(sheetAppLinks(result.spreadsheetId, result.range, data.sheetId));
      }).catch(() => { if (active && hasSavedCells) setView("saved"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [resolveTab, hasSavedCells, backendRunId, result.sourceStepKey, result.spreadsheetId, result.range]);
  const app = screen || result;
  const comparison = result.headers?.length && result.ranges?.length === 1
    ? sheetComparisonMarkdown(result.headers, result.ranges[0].values) : "";
  return <section aria-label="Google Sheets result screen" className="overflow-hidden rounded-xl border border-slate-200 bg-white">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-[#f8fafd] px-4 py-3 text-slate-700">
      <div className="flex items-center gap-2 text-sm"><Table2 className="h-5 w-5 text-emerald-700" /><span className="font-medium">{sheetRange(result.range)?.tab || "Google Sheets"}</span>{result.verified && hasSavedCells && <span className="flex items-center gap-1 text-xs text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" />Verified</span>}</div>
      <div className="flex flex-wrap items-center gap-3"><div className="flex rounded-lg border border-slate-200 bg-white p-1" role="tablist" aria-label="Spreadsheet view">
        {[['saved', 'Saved cells'], ['app', 'Google Sheets'], ...(comparison ? [['markdown', 'Markdown comparison']] : [])].map(([id, label]) => <button type="button" role="tab" aria-selected={view === id} key={id} onClick={() => setView(id)} className={`rounded-md px-3 py-1.5 text-xs font-medium ${view === id ? "bg-emerald-50 text-emerald-800" : "text-slate-600 hover:bg-slate-50"}`}>{label}</button>)}
      </div><a href={app.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-medium text-white hover:bg-emerald-800">Open in Google Sheets<ArrowUpRight className="h-3.5 w-3.5" /></a></div>
    </div>
    {view !== "app" && result.partialReadBack && <p role="note" className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs leading-5 text-amber-900">Partial saved preview: {result.ranges.map((grid) => grid.range).join(", ")}. Open Google Sheets for the complete workbook.</p>}
    {view === "app" ? loading ? <div className="flex min-h-80 items-center justify-center text-sm text-slate-600" role="status">Opening the saved Google Sheets tab…</div> : <iframe title="Google Sheets — final workflow result" src={app.embedUrl} className="block h-[min(70vh,760px)] min-h-[480px] w-full border-0 bg-white" referrerPolicy="no-referrer" onError={() => setView("saved")} /> : view === "markdown" ? <div className="max-h-[36rem] overflow-auto p-5 text-sm leading-6 text-slate-800 [&_th]:min-w-40 [&_th]:border [&_th]:bg-slate-50 [&_th]:p-3 [&_td]:min-w-48 [&_td]:border [&_td]:p-3 [&_td]:align-top"><ReactMarkdown {...documentMarkdownOptions}>{comparison}</ReactMarkdown></div> : <SavedCells key={`${result.spreadsheetId}:${result.range}`} ranges={result.ranges} initialRange={result.range} />}
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-4 py-2 text-xs text-slate-600">{hasSavedCells ? <button type="button" className="underline underline-offset-2" onClick={() => setView(view === "app" ? "saved" : "app")}>{view === "app" ? "Sheet not loading? View saved cells" : "View the Google Sheets app"}</button> : <span>Open in Google Sheets if the preview needs sign-in.</span>}<a href={app.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-emerald-700">Open Google Sheets<ArrowUpRight className="h-3.5 w-3.5" /></a></div>
    <div className="flex flex-wrap justify-between gap-2 border-t border-slate-200 bg-[#f8fafd] px-4 py-2 text-xs text-slate-600"><span>{result.range || "Workbook"}</span>{comparison && <button type="button" onClick={() => downloadTextFile("aura-verified-comparison.md", comparison)} className="font-medium text-emerald-700 underline">Download Markdown</button>}<span>{view === "app" ? "Google Sheets app" : hasSavedCells ? "Saved from the workflow’s Google Sheets read-back" : "Google Sheets workbook"}</span></div>
  </section>;
}
