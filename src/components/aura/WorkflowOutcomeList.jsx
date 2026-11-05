import { AlertTriangle, BarChart3, ExternalLink, FileText, Table2 } from "lucide-react";

const actionButton = "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-full border border-cyan-400/25 px-3 py-1.5 text-[11px] font-medium text-cyan-300 transition hover:bg-cyan-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300";

export default function WorkflowOutcomeList({ actions, onOpen, onOpenRun }) {
  if (!actions.length) return null;
  return <section aria-label="Supporting workflow actions" className="mb-6">
    <h3 className="mb-3 text-sm font-semibold">What happened</h3>
    <div className="space-y-2">{actions.map((action) => {
      const Icon = action.issue ? AlertTriangle : action.icon === "sources" ? BarChart3 : action.icon === "sheet" ? Table2 : FileText;
      return <div key={action.key} className={`flex flex-wrap items-center gap-3 rounded-xl border px-3 py-3 sm:flex-nowrap ${action.issue ? "border-amber-400/30 bg-amber-400/[0.04]" : "border-white/10 bg-[#0c121e]/65"}`}>
        <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-xl ${action.issue ? "bg-amber-400/10 text-amber-400" : "bg-violet-400/10 text-violet-400"}`}><Icon className="h-4 w-4" /></span>
        <div className="min-w-0 flex-1"><p className="text-sm font-medium">{action.count !== undefined && <strong className="mr-1.5 text-lg font-bold">{action.count}</strong>}{action.title}</p>
          <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">{action.detail}</p>
          {action.preview?.length > 0 && <div className="mt-2 space-y-1 text-xs text-muted-foreground">{action.preview.map((item, index) => <p key={index}>{item.name}{item.contacts !== null && ` · ${item.contacts.toLocaleString("en-US")} contacts`}</p>)}</div>}
        </div>
        <div className="flex flex-wrap gap-2">
          {(action.actionId || action.resume) && <button type="button" aria-label={`${action.actionLabel}: ${action.title}`} onClick={() => action.resume && onOpenRun ? onOpenRun() : onOpen(action.actionId)} className={`${actionButton} ${action.issue ? "border-amber-400/30 text-amber-300 hover:bg-amber-400/10" : ""}`}>{action.actionLabel}</button>}
          {action.link && <a href={action.link} target="_blank" rel="noopener noreferrer" className={actionButton}><ExternalLink className="h-3 w-3" />{action.linkLabel || `Open ${action.tool}`}</a>}
        </div>
      </div>;
    })}</div>
  </section>;
}
