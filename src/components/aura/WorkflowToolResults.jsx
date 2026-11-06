import { AlertTriangle, ChevronDown, ExternalLink, FileText } from "lucide-react";
import { mainToolEntry, toolOutputResult, toolResultGroups, toolResultName, toolResultStatus } from "@/lib/toolResultViews.mjs";
import { MainToolOutput, ToolResultFrame } from "./ToolResultView";
import { EvidenceValue } from "./ToolEvidence";

// One result location per tool. The Tools used controls open these same rows.
export default function WorkflowToolResults({ entries, primary, mainEntry, hasMainOutput, results, activity, backendRunId, actions, dropdowns, onOpenRun, onOpen }) {
  const primaryTool = mainEntry?.tool || toolResultName(primary.provider);
  const groups = toolResultGroups(entries);
  if (hasMainOutput && !groups.some((group) => group.tool === primaryTool)) groups.push({ tool: primaryTool, entries: [] });
  // Put the deliverable first inside What happened, below the outcome summary.
  groups.sort((a, b) => Number(b.tool === primaryTool) - Number(a.tool === primaryTool));
  return <section aria-label="Supporting workflow actions" className="mb-6">
    <h3 className="mb-3 text-sm font-semibold">What happened</h3>
    <div className="space-y-2">{groups.map(({ tool, entries: items }) => {
      const isPrimary = tool === primaryTool && hasMainOutput;
      const completed = items.filter((entry) => entry.status === "completed" && entry.hasResponse);
      const combined = isPrimary ? primary : toolOutputResult(completed, activity);
      const combinedEntry = isPrimary ? mainEntry : mainToolEntry(completed, combined || {}) || completed.at(-1);
      const showCombined = isPrimary || combined?.kind === "spreadsheet";
      const action = actions.find((item) => isPrimary ? item.actionId === "main" : items.some((entry) => entry.id === item.actionId));
      const issues = items.filter((entry) => ["failed", "blocked", "provider_error"].includes(entry.status));
      const link = (showCombined && combined?.link) || action?.link || completed.at(-1)?.link;
      const linkLabel = (showCombined && combined?.linkLabel) || action?.linkLabel || completed.at(-1)?.linkLabel;
      return <details key={tool} ref={(node) => { if (node) dropdowns.current.set(tool, node); else dropdowns.current.delete(tool); }}
        open={isPrimary || undefined} aria-label={`${tool} result dropdown`} className={`group/tool overflow-hidden rounded-xl border bg-[#0c121e]/65 ${issues.length ? "border-amber-400/30" : "border-white/10"}`}>
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-3 p-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 [&::-webkit-details-marker]:hidden">
          <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-xl ${issues.length ? "bg-amber-400/10 text-amber-400" : "bg-violet-400/10 text-violet-400"}`}>{issues.length ? <AlertTriangle className="h-4 w-4" /> : <FileText className="h-4 w-4" />}</span>
          <span className="min-w-0 flex-1"><span className="block text-sm font-semibold">{tool}</span><span className="mt-0.5 block text-[11px] leading-4 text-muted-foreground">{action ? `${action.count !== undefined ? `${action.count} ` : ""}${action.title}` : completed.length ? `${completed.length} saved ${completed.length === 1 ? "action" : "actions"}` : items.map(toolResultStatus).join(" · ")}{issues.length ? " · Needs attention" : ""}</span></span>
          {link && <a href={link} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()} className="inline-flex items-center gap-1.5 rounded-full border border-cyan-400/25 px-3 py-1.5 text-[11px] font-medium text-cyan-300 hover:bg-cyan-400/10"><ExternalLink className="h-3 w-3" />{linkLabel || `Open in ${tool}`}</a>}
          <ChevronDown aria-hidden="true" className="h-4 w-4 shrink-0 text-violet-400 group-open/tool:rotate-180" />
        </summary>
        <div className="space-y-4 border-t border-white/10 p-3 sm:p-4">
          {action?.detail && <p className="text-xs text-muted-foreground">{action.detail}</p>}
          {actions.filter((item) => item !== action && !item.issue && items.some((entry) => entry.id === item.actionId)).map((item) => <p key={item.key} className="text-xs text-muted-foreground">{item.count !== undefined ? `${item.count} ` : ""}{item.title}{item.detail ? ` · ${item.detail}` : ""}</p>)}
          {showCombined ? <ToolResultFrame tool={tool} title={combined?.title || results.title} backupNotice={combinedEntry?.backupNotice} userEdited={combinedEntry?.userEdited} synthetic={combinedEntry?.synthetic} appScreen={["spreadsheet", "ai_response"].includes(combined?.kind)}>
            <MainToolOutput entry={combinedEntry} result={combined} results={results} activity={activity} backendRunId={backendRunId} />
          </ToolResultFrame> : completed.map((entry) => <ToolResultFrame key={entry.id} tool={tool} title={entry.preview?.title || entry.action} backupNotice={entry.backupNotice} userEdited={entry.userEdited} synthetic={entry.synthetic} appScreen={entry.preview?.kind === "ai_response"} link={entry.link}>
            <MainToolOutput entry={entry} result={entry.preview || { kind: "result" }} activity={activity} backendRunId={backendRunId} />
          </ToolResultFrame>)}
          {items.filter((entry) => entry.status !== "completed").map((entry) => <section key={entry.id} aria-label={`${tool} action status`} className="rounded-lg border border-white/10 p-3 text-sm">
            <p className="font-medium">{entry.action} · {toolResultStatus(entry)}</p>
            {entry.error ? <p className="mt-2 whitespace-pre-wrap text-amber-200">{typeof entry.error === "string" ? entry.error : JSON.stringify(entry.error)}</p> : !entry.hasResponse && <p className="mt-2 text-muted-foreground">No saved response is available for this action.</p>}
            {entry.hasResponse && <EvidenceValue value={entry.response} />}
          </section>)}
          {items.length > 0 && <details className="rounded-lg border border-white/10 p-3"><summary className="cursor-pointer text-xs font-medium text-muted-foreground">Action details</summary><div className="mt-3 space-y-4">{items.map((entry) => <section key={entry.id}><p className="mb-2 text-xs font-medium">{entry.action} · {toolResultStatus(entry)}</p><EvidenceValue value={entry.response} /></section>)}</div></details>}
        </div>
      </details>;
    })}</div>
    {actions.filter((action) => action.key === "final-review").map((action) => <div key={action.key} className="mt-2 rounded-xl border border-amber-400/30 bg-amber-400/[0.04] p-3 text-sm">
      <p className="font-medium text-amber-200">{action.title}</p><p className="mt-1 text-xs text-muted-foreground">{action.detail}</p><button type="button" onClick={() => action.resume && onOpenRun ? onOpenRun() : onOpen("activity")} className="mt-2 text-xs text-cyan-300">{action.actionLabel}</button>
    </div>)}
  </section>;
}
