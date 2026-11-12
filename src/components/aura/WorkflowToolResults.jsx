import { useState } from "react";
import { AlertTriangle, Check, ChevronDown, ExternalLink, FileText, Presentation, Table2 } from "lucide-react";
import { mainToolEntry, toolOutputResult, toolResultGroups, toolResultName, toolResultStatus } from "@/lib/toolResultViews.mjs";
import { MainToolOutput } from "./ToolResultView";
import SavedToolResponse from "./SavedToolResponse";
import AdsInputResult from "./AdsInputResult";
import NativeToolView from "./NativeToolView";
import { nativeToolView } from "@/lib/nativeToolView.mjs";
import { savedToolResponse } from "@/lib/savedToolResponse.mjs";

function SourceResults({ items }) {
  const summaries = items.map(savedToolResponse);
  const metaEmpty = items.length > 1 && items.every((item) => item.tool === "Meta Ads") && summaries.some((item) => item.empty) && summaries.every((item, index) => item.empty || ["meta-ads.accounts.list", "meta-ads.identity.get"].includes(items[index].operation));
  if (!metaEmpty) return <div className="space-y-5">{items.map((entry) => <section key={entry.id}><h4 className="mb-3 text-sm font-medium">{entry.tool === "Google Ads" && savedToolResponse(entry).campaigns.length ? "Campaign performance" : entry.action}</h4><SavedToolResponse entry={entry} /></section>)}</div>;
  const withAccount = items.find((entry) => savedToolResponse(entry).facts.some((fact) => fact.label === "Account")) || items[0];
  const periods = [...new Set(summaries.flatMap((item) => item.facts.filter((fact) => fact.label === "Reporting dates").map((fact) => fact.value)))];
  return <div className="space-y-4"><SavedToolResponse entry={withAccount} />{periods.length > 0 && <div><h4 className="mb-2 text-xs font-medium text-muted-foreground">Reporting periods checked</h4><ul className="space-y-1 text-sm text-slate-200">{periods.map((period) => <li key={period}>{period}</li>)}</ul></div>}</div>;
}

export default function WorkflowToolResults({ entries, primary, mainEntry, hasMainOutput, results, activity, backendRunId, actions, dropdowns, onOpenRun, onOpen }) {
  const [canvaScreens, setCanvaScreens] = useState({});
  const primaryTool = mainEntry?.tool || toolResultName(primary.provider);
  const groups = toolResultGroups(entries);
  if (hasMainOutput && !groups.some((group) => group.tool === primaryTool)) groups.push({ tool: primaryTool, entries: [] });
  groups.sort((a, b) => Number(b.tool === primaryTool) - Number(a.tool === primaryTool));
  return <section aria-label="Supporting workflow actions" className="mb-7 space-y-5">
    <h2 className="text-sm font-semibold">Results from every tool</h2>
    {groups.map(({ tool, entries: items }) => {
      const isPrimary = tool === primaryTool && hasMainOutput;
      const completed = items.filter((entry) => entry.status === "completed" && entry.hasResponse);
      const combined = isPrimary ? primary : toolOutputResult(completed, activity);
      const combinedEntry = isPrimary ? mainEntry : mainToolEntry(completed, combined || {}) || completed.at(-1);
      const visual = combined && !["result"].includes(combined.kind);
      const adsInput = ["Google Ads", "Meta Ads", "Reddit Ads"].includes(tool) && completed.length > 0 && !visual;
      const issues = items.filter((entry) => ["failed", "blocked", "provider_error"].includes(entry.status));
      const link = combined?.link || completed.findLast((entry) => entry.link)?.link;
      const previewKey = `${combinedEntry?.runId || backendRunId}:${combinedEntry?.originalStepKey || combined?.sourceStepKey}:${combined?.designId}`;
      const native = nativeToolView(tool, completed, { ...combined, ...canvaScreens[previewKey] });
      const Icon = tool === "Canva" ? Presentation : tool === "Google Sheets" ? Table2 : FileText;
      const count = combined?.kind === "spreadsheet" ? `${combined.ranges?.length || 0} saved ranges` : combined?.pageCount ? `${combined.pageCount} ${combined.pageCount === 1 ? "slide" : "slides"}` : `${completed.length} saved ${completed.length === 1 ? "action" : "actions"}`;
      return <article key={tool} data-result-preview={visual || adsInput || undefined} className={`min-w-0 overflow-hidden rounded-2xl border ${isPrimary ? "border-violet-400/30 bg-gradient-to-br from-violet-400/[0.08] to-[#0c1420]" : "border-white/10 bg-[#0d1522]"}`}>
        <header className="flex flex-wrap items-center justify-between gap-4 p-4 sm:p-6">
          <div className="flex min-w-0 items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-400/10 text-violet-300"><Icon className="h-5 w-5" /></span><div className="min-w-0"><p className="text-xs font-medium text-violet-300">{isPrimary ? "Main output" : adsInput ? "Source data · Used as input" : "Tool result"}</p><h3 className="mt-1 text-base font-semibold">{tool}</h3><p className="mt-1 text-xs text-muted-foreground">{count}{issues.length ? " · Needs attention" : ""}</p></div></div>
          {link && !native && <a href={link} target="_blank" rel="noopener noreferrer" className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold ${isPrimary ? "bg-violet-500 text-white hover:bg-violet-400" : "border border-white/15 text-cyan-200 hover:bg-white/5"}`}>Open in {tool}<ExternalLink className="h-4 w-4" /></a>}
          {native && <NativeToolView tool={tool} model={native} isPrimary={isPrimary} />}
        </header>
        {combinedEntry?.backupNotice && <p className="mx-4 mb-4 rounded-xl border border-amber-400/20 bg-amber-400/5 p-3 text-xs leading-5 text-amber-100 sm:mx-6">Backup used · {combinedEntry.backupNotice}</p>}
        {visual && <div className="px-4 pb-4 sm:px-6 sm:pb-6"><h4 className="mb-4 break-words text-lg font-medium sm:text-xl">{combined.title}</h4><MainToolOutput entry={combinedEntry} result={combined} results={results} activity={activity} backendRunId={backendRunId} onCanvaScreen={(screen) => setCanvaScreens((current) => ({ ...current, [previewKey]: screen }))} /></div>}
        {adsInput && <div className="px-4 pb-5 sm:px-6"><AdsInputResult tool={tool} entries={completed} isPrimary={isPrimary} /></div>}
        <details ref={(node) => { if (node) dropdowns.current.set(tool, node); else dropdowns.current.delete(tool); }} aria-label={`${tool} result dropdown`} open={!isPrimary && !visual && !adsInput || undefined} className="group/tool border-t border-white/10">
          <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 sm:px-6 [&::-webkit-details-marker]:hidden"><span>{isPrimary || adsInput || visual ? "Saved actions" : "Results and reporting coverage"}</span><ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground group-open/tool:rotate-180" /></summary>
          <div className="space-y-4 px-4 pb-5 sm:px-6">
            {!visual && !adsInput && <SourceResults items={completed} />}
            {items.filter((entry) => entry.status !== "completed").map((entry) => <p key={entry.id} className="flex items-start gap-2 text-sm text-amber-200"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{entry.action} · {toolResultStatus(entry)}</p>)}
            {(isPrimary || visual || adsInput) && <ul className="space-y-3">{items.map((entry) => <li key={entry.id} className="flex items-start gap-2 text-xs leading-5 text-muted-foreground">{entry.status === "completed" ? <Check className="mt-1 h-3 w-3 shrink-0 text-emerald-400" /> : <AlertTriangle className="mt-1 h-3 w-3 shrink-0 text-amber-300" />}<span>{entry.action}<span className="block text-[11px]">{toolResultStatus(entry)}{entry.completedAt ? ` · ${new Date(entry.completedAt).toLocaleString()}` : ""}</span></span></li>)}</ul>}
            <button type="button" onClick={() => issues.length && onOpenRun ? onOpenRun() : onOpen("activity")} className="text-xs text-muted-foreground underline underline-offset-4">{issues.length && onOpenRun ? "Resolve failed step" : "View workflow activity"}</button>
          </div>
        </details>
      </article>;
    })}
    {actions.filter((action) => action.key === "final-review").map((action) => <div key={action.key} className="rounded-xl border border-amber-400/30 bg-amber-400/[0.04] p-4 text-sm"><p className="font-medium text-amber-200">{action.title}</p><p className="mt-1 text-xs text-muted-foreground">{action.detail}</p><button type="button" onClick={() => action.resume && onOpenRun ? onOpenRun() : onOpen("activity")} className="mt-2 text-xs text-cyan-300">{action.actionLabel}</button></div>)}
  </section>;
}
