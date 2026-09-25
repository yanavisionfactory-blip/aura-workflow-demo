import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, ArrowRight, CalendarClock, Check, CheckCircle2, ChevronDown, ExternalLink, FileDown, Plus, RefreshCw, Share2, Zap } from "lucide-react";
import AccessRequestModal from "./AccessRequestModal";
import ScheduleModal from "./ScheduleModal";
import CreatorApprovalList from "./CreatorApprovalList";
import ResultPreview from "./ResultPreview";
import { buildSummaryText } from "@/lib/auraSummary";
import { resultMetrics, selectPrimaryOutcome, supportingReceipts } from "@/lib/resultPresentation.mjs";

export default function ResultsView({ results, onNewWorkflow, onStartWorkflow, workflowPrompt, activity, prompt, interpretation, backendRunId, historyWorkflowId, scheduleTitle }) {
  const isFailure = results.status === "failed" || results.status === "needs_attention";
  const [showModal, setShowModal] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showSchedule, setShowSchedule] = useState(false);
  const primaryResult = useMemo(() => selectPrimaryOutcome(results), [results]);
  const metrics = useMemo(() => isFailure ? [] : resultMetrics(results.metrics || [], activity || []), [results.metrics, activity, isFailure]);
  const receipts = useMemo(() => supportingReceipts(results, activity || [], primaryResult, results.resultPresentation), [activity, primaryResult, results]);
  const creatorsOutcome = (results.outcomes || []).find((outcome) => outcome.type === "creators" && outcome.items?.length > 0);
  const nextSteps = results.nextSteps || [];
  const summaryArgs = { title: results.title, summary: results.summary, metrics, outcomes: results.outcomes, activity, prompt, interpretation, nextSteps };

  const handleShare = async () => {
    try {
      await navigator.clipboard.writeText(buildSummaryText(summaryArgs));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.warn("Could not copy the result summary", error);
    }
  };
  const handleDownload = () => {
    const blob = new Blob([buildSummaryText(summaryArgs)], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `aura-summary-${(results.title || "workflow").replace(/\s+/g, "-").toLowerCase()}.txt`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mx-auto w-full max-w-5xl pb-8">
      <div className="mb-7 flex items-start gap-4">
        <div className={`shrink-0 rounded-2xl border p-3 ${isFailure ? "border-amber-400/20 bg-amber-400/10" : "border-emerald-400/20 bg-emerald-400/10"}`}>
          {isFailure ? <AlertTriangle className="h-7 w-7 text-amber-400" /> : <CheckCircle2 className="h-7 w-7 text-emerald-400" />}
        </div>
        <div className="min-w-0">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">{results.title || "Workflow complete"}</h2>
          {results.summary && <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">{results.summary}</p>}
        </div>
      </div>

      {metrics.length > 0 && <div className="mb-7 grid gap-3 sm:grid-cols-3">
        {metrics.map((metric, index) => <div key={`${metric.label}:${index}`} className="rounded-2xl border border-white/10 bg-card/60 px-5 py-4">
          <p className="text-3xl font-semibold tracking-tight text-foreground">{metric.value}</p>
          <p className="mt-1 text-xs text-muted-foreground">{metric.label}</p>
        </div>)}
      </div>}

      <section className="mb-5 overflow-hidden rounded-3xl border border-primary/25 bg-gradient-to-br from-primary/[0.09] via-card/80 to-card/50 shadow-xl shadow-primary/[0.06]">
        <div className="flex flex-wrap items-start justify-between gap-4 px-5 pb-4 pt-6 sm:px-7">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary">Your result</p>
            <h3 className="text-xl font-semibold">{primaryResult.title || results.title || "Workflow result"}</h3>
            {primaryResult.provider && <p className="mt-1.5 text-xs text-muted-foreground">{primaryResult.providerVerb || "Created in"} {primaryResult.provider}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            {primaryResult.link && <a href={primaryResult.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary/90"><ExternalLink className="h-4 w-4" />{primaryResult.linkLabel || "Open result"}</a>}
            {primaryResult.artifact?.link && <a href={primaryResult.artifact.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-primary/30 px-4 py-2.5 text-sm font-medium text-primary hover:bg-primary/10"><ExternalLink className="h-4 w-4" />{primaryResult.artifact.linkLabel || "Open presentation"}</a>}
          </div>
        </div>
        <div className="px-5 pb-6 sm:px-7"><ResultPreview result={primaryResult} results={results} /></div>
        {primaryResult.artifact && <div className="flex items-center justify-between gap-3 border-t border-white/10 px-5 py-3 text-xs sm:px-7">
          <span>Presentation · {primaryResult.artifact.title}</span>
          <span className="text-emerald-400">{primaryResult.artifactDelivered ? "Attached and delivered" : "Created in Canva"}</span>
        </div>}
      </section>

      {receipts.length > 0 && <details className="group mb-8 overflow-hidden rounded-2xl border border-white/10 bg-card/40">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4 marker:hidden [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-3 text-sm font-medium"><CheckCircle2 className="h-4 w-4 text-emerald-400" />Results from other apps <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-muted-foreground">{receipts.length}</span></span>
          <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>
        <div className="grid gap-3 border-t border-white/10 p-4 sm:grid-cols-2">
          {receipts.map((receipt) => <div key={receipt.key} className="rounded-xl border border-white/10 bg-[#0c1422] p-4">
            <p className="text-xs font-semibold text-primary">{receipt.tool}</p>
            <p className="mt-1 text-sm font-medium">{receipt.title}</p>
            {receipt.preview?.length > 0 && <div className="mt-3 space-y-2 border-t border-white/10 pt-3">
              {receipt.preview.map((audience, index) => <div key={index} className="flex items-start justify-between gap-3 text-xs">
                <span className="break-words">{audience.name}</span>
                {audience.contacts !== null && <span className="shrink-0 text-muted-foreground">{audience.contacts.toLocaleString("en-US")} contacts</span>}
              </div>)}
            </div>}
            {receipt.link && <a href={receipt.link} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline">{receipt.linkLabel || `Open ${receipt.tool}`}<ExternalLink className="h-3 w-3" /></a>}
          </div>)}
        </div>
      </details>}

      {creatorsOutcome && <CreatorApprovalList items={creatorsOutcome.items} />}
      {!isFailure && nextSteps.length > 0 && <section className="mb-6">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><ArrowRight className="h-4 w-4 text-primary" />Suggested next</h3>
        <div className="flex flex-wrap gap-2">{nextSteps.map((step, index) => <button key={index} type="button" onClick={() => onStartWorkflow(step)} className="rounded-full border border-primary/25 bg-primary/[0.05] px-4 py-2 text-xs text-primary hover:bg-primary/10">{step}</button>)}</div>
      </section>}
      <section className="rounded-2xl border border-white/10 bg-card/40 p-5 sm:p-6">
        <h3 className="font-semibold">What would you like to do next?</h3>
        <p className="mt-1 text-sm text-muted-foreground">{isFailure ? "Your completed work is saved. Try again or start a new workflow." : "Continue from this result or create something new."}</p>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <button type="button" onClick={() => onStartWorkflow(prompt)} className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium hover:bg-white/10"><RefreshCw className="h-4 w-4" />Run again</button>
          {!isFailure && backendRunId && <button type="button" onClick={() => setShowSchedule(true)} className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-white hover:bg-primary/90"><CalendarClock className="h-4 w-4" />Schedule</button>}
          <button type="button" onClick={onNewWorkflow} className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium hover:bg-white/10"><Plus className="h-4 w-4" />New workflow</button>
        </div>
      </section>

      <div className="mt-5 flex flex-wrap items-center gap-5 border-t border-white/10 pt-5 text-xs text-muted-foreground">
        {activity?.length > 0 && <details className="group relative"><summary className="flex cursor-pointer list-none items-center gap-1.5 hover:text-foreground [&::-webkit-details-marker]:hidden"><Activity className="h-4 w-4" />Activity<ChevronDown className="h-3 w-3 group-open:rotate-180" /></summary><ol className="absolute bottom-full left-0 z-10 mb-2 max-h-56 w-72 overflow-y-auto rounded-xl border border-white/10 bg-[#121725] p-3 shadow-xl">{activity.map((step, index) => <li key={step.id || index} className="flex items-start gap-2 py-1.5 text-xs"><CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" /><span>{step.action || step.tool || "Completed"}</span></li>)}</ol></details>}
        <button type="button" onClick={handleShare} className="inline-flex items-center gap-1.5 hover:text-foreground">{copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Share2 className="h-4 w-4" />}{copied ? "Copied" : "Share"}</button>
        {primaryResult.downloadUrl
          ? <a href={primaryResult.downloadUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 hover:text-foreground"><FileDown className="h-4 w-4" />Download result</a>
          : <button type="button" onClick={handleDownload} className="inline-flex items-center gap-1.5 hover:text-foreground"><FileDown className="h-4 w-4" />Download summary</button>}
        {!isFailure && !backendRunId && <button type="button" onClick={() => setShowModal(true)} className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 font-semibold text-white"><Zap className="h-4 w-4" />Connect & run for real</button>}
      </div>
      {!backendRunId && <AccessRequestModal open={showModal} onClose={() => setShowModal(false)} workflowPrompt={workflowPrompt} />}
      <ScheduleModal open={showSchedule} onClose={() => setShowSchedule(false)} title={scheduleTitle || results.title} backendRunId={backendRunId} historyWorkflowId={historyWorkflowId} />
    </motion.div>
  );
}
