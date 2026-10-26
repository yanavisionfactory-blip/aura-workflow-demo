import { useEffect, useState } from "react";
import { AlertTriangle, ArrowUpRight, CheckCircle2, ChevronRight, FileText, Maximize2, Wrench } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { toolResultGroups, toolResultName, toolResultStatus } from "@/lib/toolResultViews.mjs";
import ResultPreview from "./ResultPreview";
import ToolEvidence, { EvidenceValue } from "./ToolEvidence";

export function ToolResultFrame({ tool, title, synthetic = false, onExpand, children, expanded = false, appScreen = false }) {
  return <section aria-label={`${toolResultName(tool)} output preview`} className="overflow-hidden rounded-xl border border-white/15 bg-[#0b1320]">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 bg-white/[0.03] px-4 py-3">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary"><FileText className="h-4 w-4" /></span>
        <div className="min-w-0"><p className="text-xs font-semibold">{toolResultName(tool)}</p><p className="truncate text-xs text-muted-foreground">{title}</p></div>
      </div>
      <div className="flex items-center gap-3">
        {synthetic && <span className="rounded-full border border-violet-400/25 px-2 py-1 text-[10px] text-violet-200">Synthetic data</span>}
        {onExpand && <button type="button" onClick={onExpand} className="inline-flex items-center gap-1.5 text-xs font-medium text-primary"><Maximize2 className="h-3.5 w-3.5" />Open tool view</button>}
      </div>
    </header>
    <div tabIndex={0} aria-label={`${title} content`} className={`${expanded || appScreen ? "min-h-0 flex-1" : "max-h-[30rem]"} overflow-auto overscroll-contain outline-offset-[-2px] ${appScreen ? "p-0" : "p-3 sm:p-5"}`}>{children}</div>
  </section>;
}

export function ResultsByTool({ entries, onOpen }) {
  if (!entries.length) return null;
  const attention = entries.filter((entry) => ["failed", "blocked", "provider_error"].includes(entry.status)).length;
  return <section aria-label="Results by tool" className="mb-6 rounded-xl border border-white/10 bg-card/30 p-4 sm:p-5">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold"><Wrench className="h-4 w-4 text-muted-foreground" />Tools used</h3>
      <button type="button" onClick={() => onOpen("activity")} className="text-xs font-medium text-primary">View activity</button>
    </div>
    <div className="flex flex-wrap gap-2">{toolResultGroups(entries).map(({ tool, entries: items }) =>
      <button type="button" key={tool} aria-label={`View ${tool} results`} onClick={() => onOpen(items[0].id)} className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs hover:border-primary/40 hover:bg-primary/10">
        <span>{tool}</span><span className="text-muted-foreground">{items.length}</span><ChevronRight className="h-3 w-3 text-muted-foreground" />
      </button>)}
    </div>
    {attention > 0 && <p className="mt-3 flex items-center gap-2 text-xs text-amber-200"><AlertTriangle className="h-3.5 w-3.5" />{attention} {attention === 1 ? "action needs" : "actions need"} attention. Open its tool result for details.</p>}
  </section>;
}

function SourceOutput({ entry }) {
  const source = entry.source;
  const comparison = entry.response?.comparison;
  return <div className="space-y-5">
    <div><h3 className="text-lg font-semibold">{source.name}</h3><p className="mt-1 text-xs leading-6 text-muted-foreground">{source.filename} · {source.timezone} · {source.currency}</p></div>
    {entry.response?.receipt?.provider_api_called === false && <p className="rounded-lg border border-violet-400/25 bg-violet-400/5 p-3 text-sm leading-6 text-violet-100">AURA processed this supplied {entry.synthetic ? "synthetic " : ""}export. {source.name}'s reporting API was not called.</p>}
    {comparison && <div className="overflow-auto rounded-lg border border-white/10"><table className="w-full text-left text-sm"><thead className="bg-white/5"><tr><th className="p-3">Metric</th><th className="p-3">Previous week</th><th className="p-3">Latest week</th></tr></thead><tbody>{Object.keys(comparison.current || {}).map((key) => <tr key={key} className="border-t border-white/10"><th className="p-3 font-medium">{key}</th>{[comparison.previous?.[key], comparison.current?.[key]].map((value, i) => <td className="p-3 tabular-nums" key={i}>{typeof value === "number" ? value.toLocaleString("en-US", { maximumFractionDigits: 4 }) : value ?? "Unavailable"}</td>)}</tr>)}</tbody></table></div>}
    <div><h4 className="mb-3 font-semibold">Source rows</h4><EvidenceValue value={source.rows} /></div>
    {source.searchTerms?.length > 0 && <div><h4 className="mb-3 font-semibold">Search terms</h4><p className="mb-3 text-xs text-muted-foreground">Breakdown rows; do not add these to the campaign totals.</p><EvidenceValue value={source.searchTerms} /></div>}
    <p className="text-xs leading-6 text-muted-foreground">{source.attribution} · {source.dateBasis}<br />{source.caution}</p>
  </div>;
}

export function MainToolOutput({ entry, result, results, activity, backendRunId }) {
  if (entry?.source) return <SourceOutput entry={entry} />;
  if ((!result.kind || result.kind === "result") && !results.breakdown && !result.items?.length && entry?.hasResponse) return <EvidenceValue value={entry.response} />;
  return <ResultPreview result={result} results={results} activity={activity} backendRunId={backendRunId} />;
}

export default function ToolResultDialog({ request, onClose, entries, primary, mainEntry, hasMainOutput, results, activity, backendRunId }) {
  const [selected, setSelected] = useState(request?.id || "main");
  useEffect(() => { if (request) setSelected(request.id); }, [request]);
  const entry = entries.find((item) => item.id === selected);
  const isMain = selected === "main";
  const isActivity = selected === "activity";
  const tool = isMain ? toolResultName(primary.provider || mainEntry?.tool) : entry?.tool;
  const title = isMain ? primary.title || results.title : entry?.action || "Workflow activity";
  const group = entries.filter((item) => item.tool === tool);
  const link = isMain ? primary.link : entry?.link;
  return <Dialog open={Boolean(request)} onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="flex h-[90dvh] w-[calc(100vw-2rem)] max-w-6xl flex-col gap-0 overflow-hidden rounded-2xl border-white/15 bg-[#0a111d] p-0">
      <div className="border-b border-white/10 px-5 py-4 pr-12"><DialogTitle>Tool results</DialogTitle><DialogDescription className="mt-1.5">Review the main output and the saved actions from each tool.</DialogDescription></div>
      <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
        <nav aria-label="Tool result navigation" className="flex shrink-0 gap-2 overflow-auto border-b border-white/10 p-3 sm:w-56 sm:flex-col sm:border-b-0 sm:border-r">
          {hasMainOutput && <button type="button" aria-current={isMain ? "page" : undefined} onClick={() => setSelected("main")} className={`shrink-0 rounded-lg px-3 py-2.5 text-left text-xs ${isMain ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-white/5"}`}>Main output</button>}
          {toolResultGroups(entries).map(({ tool: name, entries: items }) => <button type="button" key={name} aria-current={!isMain && !isActivity && tool === name ? "page" : undefined} onClick={() => setSelected(items[0].id)} className={`flex shrink-0 items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left text-xs ${!isMain && tool === name ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-white/5"}`}><span>{name}</span><span>{items.length}</span></button>)}
          <button type="button" aria-current={isActivity ? "page" : undefined} onClick={() => setSelected("activity")} className={`shrink-0 rounded-lg px-3 py-2.5 text-left text-xs ${isActivity ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-white/5"}`}>Workflow activity</button>
        </nav>
        <div className="min-h-0 min-w-0 flex-1 overflow-auto p-4 sm:p-5">
          {isActivity ? <ToolEvidence activity={activity} initiallyOpen /> : <>
            {entry && <div aria-label={`${tool} actions`} className="mb-4 flex flex-wrap gap-2">{group.map((item) => <button type="button" key={item.id} aria-pressed={selected === item.id} onClick={() => setSelected(item.id)} className={`rounded-lg border px-3 py-2 text-left text-xs ${selected === item.id ? "border-primary/40 bg-primary/10 text-primary" : "border-white/10 text-muted-foreground"}`}>{item.action}<span className="mt-1 block opacity-70">{toolResultStatus(item)}</span></button>)}</div>}
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><p className="mb-1 text-xs text-primary">{tool}</p><h3 className="break-words text-lg font-semibold">{title}</h3></div>
              {entry && <span className="flex items-center gap-1.5 text-xs text-muted-foreground">{entry.status === "completed" ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <AlertTriangle className="h-4 w-4 text-amber-300" />}{toolResultStatus(entry)}</span>}
              {link && <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary">Open in {tool}<ArrowUpRight className="h-3.5 w-3.5" /></a>}
            </div>
            {isMain ? <ToolResultFrame tool={tool} title={title} synthetic={mainEntry?.synthetic} expanded><MainToolOutput entry={mainEntry} result={primary} results={results} activity={activity} backendRunId={backendRunId} /></ToolResultFrame> : entry ? <>
              {entry.synthetic && <p className="mb-4 rounded-lg border border-violet-400/25 p-3 text-xs text-violet-100">Synthetic data · saved AURA result</p>}
              {entry.error && <p role="status" className="mb-4 whitespace-pre-wrap rounded-lg bg-amber-400/10 p-3 text-sm text-amber-200">{typeof entry.error === "string" ? entry.error : JSON.stringify(entry.error)}</p>}
              {entry.source ? <SourceOutput entry={entry} /> : entry.preview ? <ResultPreview result={entry.preview} results={{ summary: entry.action }} /> : entry.hasResponse ? <EvidenceValue value={entry.response} /> : <p className="text-sm text-muted-foreground">No provider response is saved for this action. This does not mean the tool returned zero results.</p>}
              <details className="mt-5 rounded-lg border border-white/10 p-3"><summary className="cursor-pointer text-xs font-semibold">Action details</summary><p className="my-3 break-all text-xs text-muted-foreground">{entry.operation}{entry.completedAt && ` · ${entry.completedAt}`}</p><h4 className="mb-3 text-xs font-semibold">Inputs used</h4><EvidenceValue value={entry.inputs} />{(entry.preview || entry.source) && <><h4 className="my-3 text-xs font-semibold">Saved response</h4><EvidenceValue value={entry.response} /></>}</details>
            </> : <p className="text-sm text-muted-foreground">This action is not available in the saved workflow.</p>}
          </>}
        </div>
      </div>
    </DialogContent>
  </Dialog>;
}
