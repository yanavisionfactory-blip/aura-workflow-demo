import { useEffect, useState } from "react";
import { ArrowUpRight, CheckCircle2, Table2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { documentMarkdownOptions } from "@/lib/documentMarkdown.mjs";
import { columnName, sheetAppLinks, sheetRange } from "@/lib/googleSheetsResult.mjs";
import { auraRequest } from "@/lib/auraApi";
import { sheetComparisonMarkdown } from "@/lib/sheetReviewEdit.mjs";
import { downloadTextFile } from "@/lib/auraDownload";

function SavedCells({ ranges = [] }) {
  const [tab, setTab] = useState(0);
  const grid = ranges[tab];
  const [selected, setSelected] = useState(null);
  if (!grid) return <p className="p-6 text-sm text-slate-600">No cell preview was saved for this action. Open the Google Sheet to see its contents.</p>;
  const origin = sheetRange(grid.range);
  const columns = Math.max(1, ...grid.values.map((row) => row.length));
  const longCells = grid.values.flatMap((row, r) => row.map((value, c) => ({ r, c, value })))
    .filter((cell) => typeof cell.value === "string" && cell.value.length > 200).sort((a, b) => b.value.length - a.value.length);
  const active = selected || longCells[0];
  const address = (r, c) => `${columnName(origin.column + c)}${origin.row + r}`;
  return <div className="bg-white text-slate-800">
    <div className="flex flex-wrap gap-1 border-b border-slate-200 bg-[#f8fafd] px-3 pt-2" role="tablist" aria-label="Saved sheet ranges">
      {ranges.map((item, index) => <button type="button" role="tab" aria-selected={index === tab} key={`${item.range}-${index}`} onClick={() => { setTab(index); setSelected(null); }} className={`rounded-t-lg px-4 py-2.5 text-xs font-medium ${index === tab ? "border-b-2 border-emerald-700 bg-emerald-50 text-emerald-800" : "text-slate-600"}`}>{sheetRange(item.range)?.tab || item.range}</button>)}
    </div>
    <div className="max-h-80 overflow-auto" aria-label="Saved Google Sheets cells">
      <table className="w-full border-collapse text-left text-xs"><thead className="sticky top-0 z-10 bg-[#f1f3f4] text-slate-600"><tr><th className="w-12 border border-slate-200" />{Array.from({ length: columns }, (_, c) => <th key={c} className="border border-slate-200 px-3 py-2 text-center font-normal">{columnName(origin.column + c)}</th>)}</tr></thead>
        <tbody>{grid.values.map((row, r) => <tr key={r}><th className="w-12 border border-slate-200 bg-[#f1f3f4] px-3 py-2 text-center font-normal text-slate-500">{origin.row + r}</th>{Array.from({ length: columns }, (_, c) => <td key={c} className={`min-w-36 max-w-xl border border-slate-200 align-top ${active?.r === r && active?.c === c ? "bg-blue-50 outline outline-2 -outline-offset-2 outline-blue-500" : ""}`}>
          <button type="button" aria-label={`Cell ${address(r, c)}`} onClick={() => setSelected({ r, c, value: row[c] ?? "" })} className="block w-full px-3 py-2 text-left"><span className="line-clamp-3 whitespace-pre-wrap break-words">{String(row[c] ?? "") || "\u00a0"}</span></button>
        </td>)}</tr>)}</tbody>
      </table>
    </div>
    {active && <section aria-label="Selected cell contents" className="border-t border-slate-200">
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
  const [view, setView] = useState("saved");
  const [screen, setScreen] = useState(null);
  const [loading, setLoading] = useState(Boolean(backendRunId && result.sourceStepKey && !Number.isInteger(result.sheetId)));
  useEffect(() => {
    if (!backendRunId || !result.sourceStepKey || Number.isInteger(result.sheetId)) return;
    let active = true;
    setLoading(true);
    auraRequest(`/v1/runs/${encodeURIComponent(backendRunId)}/steps/${encodeURIComponent(result.sourceStepKey)}/sheet-screen`, { timeoutMs: 20000 })
      .then((data) => {
        if (!active) return;
        if (data.spreadsheetId !== result.spreadsheetId || !Number.isInteger(data.sheetId) || data.sheetId < 0) throw new Error("Unmatched spreadsheet tab");
        setScreen(sheetAppLinks(result.spreadsheetId, result.range, data.sheetId));
      }).catch(() => { if (active) setView("saved"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [backendRunId, result.sourceStepKey, result.sheetId, result.spreadsheetId, result.range]);
  const app = screen || result;
  const comparison = result.headers?.length && result.ranges?.length === 1
    ? sheetComparisonMarkdown(result.headers, result.ranges[0].values) : "";
  return <section aria-label="Google Sheets result screen" className="overflow-hidden rounded-xl border border-slate-200 bg-white">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-[#f8fafd] px-4 py-3 text-slate-700">
      <div className="flex items-center gap-2 text-sm"><Table2 className="h-5 w-5 text-emerald-700" /><span className="font-medium">{sheetRange(result.range)?.tab || "Google Sheets"}</span>{result.verified && <span className="flex items-center gap-1 text-xs text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" />Verified</span>}</div>
      <div className="flex flex-wrap items-center gap-3"><div className="flex rounded-lg border border-slate-200 bg-white p-1" role="tablist" aria-label="Spreadsheet view">
        {[['app', 'Google Sheets'], ['saved', 'Saved cells'], ...(comparison ? [['markdown', 'Markdown comparison']] : [])].map(([id, label]) => <button type="button" role="tab" aria-selected={view === id} key={id} onClick={() => setView(id)} className={`rounded-md px-3 py-1.5 text-xs font-medium ${view === id ? "bg-emerald-50 text-emerald-800" : "text-slate-600 hover:bg-slate-50"}`}>{label}</button>)}
      </div><a href={app.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-medium text-white hover:bg-emerald-800">Open in Google Sheets<ArrowUpRight className="h-3.5 w-3.5" /></a></div>
    </div>
    {view === "app" ? loading ? <div className="flex min-h-80 items-center justify-center text-sm text-slate-600" role="status">Opening the saved Google Sheets tab…</div> : <iframe title="Google Sheets — final workflow result" src={app.embedUrl} className="block h-[min(70vh,760px)] min-h-[480px] w-full border-0 bg-white" referrerPolicy="no-referrer" onError={() => setView("saved")} /> : view === "markdown" ? <div className="max-h-[36rem] overflow-auto p-5 text-sm leading-6 text-slate-800 [&_th]:min-w-40 [&_th]:border [&_th]:bg-slate-50 [&_th]:p-3 [&_td]:min-w-48 [&_td]:border [&_td]:p-3 [&_td]:align-top"><ReactMarkdown {...documentMarkdownOptions}>{comparison}</ReactMarkdown></div> : <SavedCells ranges={result.ranges} />}
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-4 py-2 text-xs text-slate-600"><button type="button" className="underline underline-offset-2" onClick={() => setView(view === "app" ? "saved" : "app")}>{view === "app" ? "Sheet not loading? View saved cells" : "View the Google Sheets app"}</button><a href={app.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-emerald-700">Open Google Sheets<ArrowUpRight className="h-3.5 w-3.5" /></a></div>
    <div className="flex flex-wrap justify-between gap-2 border-t border-slate-200 bg-[#f8fafd] px-4 py-2 text-xs text-slate-600"><span>{result.range || "Workbook"}</span>{comparison && <button type="button" onClick={() => downloadTextFile("aura-verified-comparison.md", comparison)} className="font-medium text-emerald-700 underline">Download Markdown</button>}<span>{view === "app" ? "Google Sheets app" : "Saved from the workflow’s Google Sheets read-back"}</span></div>
  </section>;
}
