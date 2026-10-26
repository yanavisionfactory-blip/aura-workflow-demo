import { useId, useState } from "react";
import { ArrowUpRight, CheckCircle2, Sparkles, Table2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { documentMarkdownOptions } from "@/lib/documentMarkdown.mjs";
import { columnName, sheetAppLinks, sheetRange } from "@/lib/googleSheetsResult.mjs";
import { toolResultEntries } from "@/lib/toolResultViews.mjs";

export function PreparedReports({ activity = [] }) {
  const reports = toolResultEntries(activity).filter((entry) => entry.preview?.kind === "report");
  return reports.map((entry) => <section key={entry.id} aria-label={`${entry.tool} prepared output`} className="mt-5 overflow-hidden rounded-2xl border border-white/15 bg-white text-slate-800">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-5 py-4">
      <div className="flex items-center gap-3"><span className="rounded-xl bg-slate-900 p-2.5 text-white"><Sparkles className="h-5 w-5" /></span><div><h3 className="text-sm font-semibold">{entry.tool}</h3><p className="mt-0.5 text-xs text-slate-500">{entry.preview.title}</p></div></div>
      <span className="flex items-center gap-1.5 text-xs text-emerald-700"><CheckCircle2 className="h-4 w-4" />Response ready</span>
    </header>
    <div tabIndex={0} aria-label={`${entry.tool} comparison`} className="max-h-[30rem] overflow-auto p-5 text-sm leading-7 sm:p-7 [&_h1]:mb-4 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-3 [&_h2]:mt-5 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mt-4 [&_h3]:font-semibold [&_p]:mb-3 [&_table]:my-4 [&_table]:block [&_table]:overflow-auto [&_th]:min-w-40 [&_th]:border [&_th]:border-slate-200 [&_th]:bg-slate-50 [&_th]:p-3 [&_td]:min-w-56 [&_td]:border [&_td]:border-slate-200 [&_td]:p-3 [&_td]:align-top [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_a]:text-blue-700 [&_a]:underline">
      <ReactMarkdown {...documentMarkdownOptions}>{entry.preview.preview.body}</ReactMarkdown>
    </div>
    <p className="border-t border-slate-200 bg-slate-50 px-5 py-2 text-xs text-slate-500">Actual response from this workflow · Review the matching spreadsheet rows below</p>
  </section>);
}

export const hasSheetRows = (args = {}) => Array.isArray(args.values) && args.values.length > 0
  && args.values.every((row) => Array.isArray(row) && row.every((cell) => cell == null || ["string", "number", "boolean"].includes(typeof cell)));

export default function SheetActionReview({ args, editing, onChange, activity = [], canEdit = true }) {
  const fieldId = useId();
  const [selected, setSelected] = useState(null);
  const origin = sheetRange(args.range) || { column: 0, tab: String(args.range || "").split("!")[0].replace(/^'|'$/g, "") };
  const rows = args.values;
  const width = Math.max(0, ...rows.map((row) => row.length));
  const id = /^[A-Za-z0-9_-]+$/.test(args.spreadsheet_id || "") ? args.spreadsheet_id : null;
  const read = toolResultEntries(activity).flatMap((entry) => entry.preview?.kind === "spreadsheet"
    && entry.preview.spreadsheetId === id ? entry.preview.ranges || [] : []);
  const header = read.find((grid) => {
    const range = sheetRange(grid.range);
    return range?.tab === origin.tab && range.row === 1 && range.column <= origin.column;
  });
  const headerOffset = origin.column - (sheetRange(header?.range)?.column || 0);
  const active = selected || { row: 0, column: 0 };
  const cellLabel = (r, c) => `${columnName(origin.column + c)} · new row ${r + 1}`;
  return <section aria-label="Google Sheets action preview" className="overflow-hidden rounded-xl border border-slate-200 bg-white text-slate-800">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-[#f8fafd] px-4 py-3">
      <div className="flex items-center gap-3"><Table2 className="h-6 w-6 text-emerald-700" /><div><h3 className="text-sm font-semibold">Google Sheets</h3><p className="mt-0.5 text-xs text-slate-500">{origin.tab || "Selected sheet"}</p></div></div>
      {id && <a href={sheetAppLinks(id, args.range).link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700">Open destination<ArrowUpRight className="h-3.5 w-3.5" /></a>}
    </header>
    <div className="flex flex-wrap justify-between gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-900"><span>Preview · {rows.length} new {rows.length === 1 ? "row" : "rows"} · {width} columns</span><span>Not saved yet</span></div>
    <div className="max-h-80 overflow-auto" tabIndex={0} aria-label="Rows to append">
      <table className="w-full border-collapse text-left text-xs"><thead className="sticky top-0 z-10 bg-[#f1f3f4]"><tr><th className="border border-slate-200 px-3 py-2 font-normal text-slate-500">New</th>{Array.from({ length: width }, (_, c) => <th key={c} className="min-w-40 border border-slate-200 px-3 py-2 font-medium"><span className="block text-center font-normal text-slate-500">{columnName(origin.column + c)}</span>{header?.values[0]?.[headerOffset + c] != null && <span className="mt-1 block">{String(header.values[0][headerOffset + c])}</span>}</th>)}</tr></thead>
        <tbody>{rows.map((row, r) => <tr key={r}><th className="border border-slate-200 bg-[#f1f3f4] px-3 py-2 text-center font-normal text-slate-500">+{r + 1}</th>{Array.from({ length: width }, (_, c) => <td key={c} className={`min-w-48 max-w-80 border border-slate-200 align-top ${active.row === r && active.column === c ? "bg-blue-50 outline outline-2 -outline-offset-2 outline-blue-500" : ""}`}>
          <button type="button" aria-label={cellLabel(r, c)} onClick={() => setSelected({ row: r, column: c })} className="block w-full px-3 py-3 text-left"><span className="line-clamp-4 whitespace-pre-wrap break-words">{String(row[c] ?? "") || "\u00a0"}</span></button>
        </td>)}</tr>)}</tbody>
      </table>
    </div>
    <div className="border-t border-slate-200 px-4 py-3"><label className="mb-2 block text-xs font-medium text-slate-500" htmlFor={fieldId}>{cellLabel(active.row, active.column)} · Complete cell</label>
      {editing && canEdit ? <textarea id={fieldId} className="min-h-28 w-full rounded-lg border border-slate-300 bg-white p-3 text-sm leading-6 outline-blue-500" value={String(rows[active.row]?.[active.column] ?? "")} onChange={(event) => onChange({ ...args, values: rows.map((row, r) => r === active.row ? Array.from({ length: Math.max(row.length, active.column + 1) }, (_, c) => c === active.column ? event.target.value : row[c] ?? "") : row) })} />
        : <p id={fieldId} className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-sm leading-6">{String(rows[active.row]?.[active.column] ?? "") || "Empty cell"}</p>}
    </div>
    <footer className="border-t border-slate-200 bg-[#f8fafd] px-4 py-2 text-xs text-slate-500">Exact values prepared for append · Select any cell to read it in full</footer>
  </section>;
}
