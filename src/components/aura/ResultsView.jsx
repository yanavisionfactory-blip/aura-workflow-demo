import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, ArrowRight, CalendarClock, Check, CheckCircle2, ChevronDown, Clock, ExternalLink, FileDown, Plus, RefreshCw, Share2, Zap } from "lucide-react";
import AccessRequestModal from "./AccessRequestModal";
import ScheduleModal from "./ScheduleModal";
import CreatorApprovalList from "./CreatorApprovalList";
import ResultPreview from "./ResultPreview";
import PrimaryResult from "./PrimaryResult";
import ToolResultDialog, { MainToolOutput, ResultsByTool, ToolResultFrame } from "./ToolResultView";
import { ResultsHeading, ResultsMetrics } from "./ResultsSummary";
import { buildSummaryText } from "@/lib/auraSummary";
import { resultMetrics, selectPrimaryOutcome, supportingReceipts, visualResultChoices } from "@/lib/resultPresentation.mjs";
import { mainToolEntry, toolResultEntries, toolResultName } from "@/lib/toolResultViews.mjs";

export default function ResultsView({ results, onNewWorkflow, onStartWorkflow, workflowPrompt, activity, prompt, interpretation, backendRunId, historyWorkflowId, scheduleTitle }) {
  const isFailure = results.status === "failed" || results.status === "needs_attention";
  const [showModal, setShowModal] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showSchedule, setShowSchedule] = useState(false);
  const [toolView, setToolView] = useState(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const visualChoices = useMemo(() => visualResultChoices(activity || [], { title: results.title, summary: results.summary }), [activity, results]);
  const selectedVisual = visualChoices.find((choice) => choice.key === searchParams.get("main"));
  const primaryResult = selectedVisual?.result || selectPrimaryOutcome(results);
  const toolEntries = useMemo(() => toolResultEntries(activity || []), [activity]);
  const mainEntry = useMemo(() => mainToolEntry(toolEntries, primaryResult, results.resultPresentation), [toolEntries, primaryResult, results.resultPresentation]);
  const hasMainOutput = Boolean((primaryResult.kind && primaryResult.kind !== "result") || primaryResult.provider || mainEntry?.hasResponse || results.breakdown || primaryResult.items?.length);
  const openTool = (id) => setToolView({ id });
  const nativeAudit = primaryResult.kind === "seo_audit";
  const approvedWeekly = primaryResult.kind === "weekly_review" && (primaryResult.packet?.version === 2 || primaryResult.packet?.provenance === "approved_export");
  const nativeResult = nativeAudit || ["weekly_review", "executive_review", "website_content"].includes(primaryResult.kind);
  const metrics = useMemo(() => isFailure ? [] : resultMetrics(results.metrics || [], activity || []), [results.metrics, activity, isFailure]);
  const receipts = useMemo(() => supportingReceipts(results, activity || [], primaryResult, results.resultPresentation, mainEntry?.id), [activity, primaryResult, results, mainEntry]);
  const creatorsOutcome = (results.outcomes || []).find((outcome) => outcome.type === "creators" && outcome.items?.length > 0);
  const nextSteps = primaryResult.kind === "website_content" ? [
    "Review the changes to each page.",
    "Check image permissions and choose a reviewer.",
    "Prepare a developer handoff after the pages are approved.",
  ] : results.nextSteps || [];
  const artifactDelivery = primaryResult.delivery || (primaryResult.artifact ? primaryResult : null);
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
    const body = primaryResult.preview?.body;
    const blob = new Blob([body || buildSummaryText(summaryArgs)], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `aura-${body ? "output" : "summary"}-${(results.title || "workflow").replace(/\s+/g, "-").toLowerCase()}.txt`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className={`mx-auto w-full pb-8 ${nativeAudit ? "max-w-3xl" : primaryResult.kind === "website_content" ? "max-w-6xl" : "max-w-5xl"}`}>
      {!nativeResult && <ResultsHeading eyebrow="Workflow result" title={results.title || "Workflow complete"} summary={results.summary} isFailure={isFailure} />}
      {!nativeResult && <ResultsMetrics metrics={metrics} />}

      {visualChoices.length > 0 && <label className="mb-5 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
        Main result
        <select aria-label="Main result" value={selectedVisual?.key || ""} onChange={(event) => {
          const next = new URLSearchParams(searchParams);
          if (event.target.value) next.set("main", event.target.value); else next.delete("main");
          setSearchParams(next, { replace: true });
        }} className="max-w-full rounded-xl border border-white/10 bg-card px-3 py-2 text-foreground">
          <option value="">Workflow summary</option>
          {visualChoices.map((choice) => <option key={choice.key} value={choice.key}>{choice.label}</option>)}
        </select>
      </label>}

      {nativeResult ? <ResultPreview result={primaryResult} results={results} activity={activity} backendRunId={backendRunId} /> : <PrimaryResult
        title={primaryResult.title || results.title || "Workflow result"}
        provider={primaryResult.provider}
        providerVerb={primaryResult.providerVerb}
        actions={<>
          {primaryResult.link && <a href={primaryResult.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary/90"><ExternalLink className="h-4 w-4" />{primaryResult.linkLabel || "Open result"}</a>}
          {primaryResult.artifact?.link && <a href={primaryResult.artifact.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-primary/30 px-4 py-2.5 text-sm font-medium text-primary hover:bg-primary/10"><ExternalLink className="h-4 w-4" />{primaryResult.artifact.linkLabel || "Open presentation"}</a>}
        </>}
        footer={artifactDelivery && <><span>Presentation · {primaryResult.artifact?.title || primaryResult.title}</span><span className="text-emerald-400">{artifactDelivery.artifactDelivered ? "Attached and delivered" : "Created in Canva"}</span></>}
      >
        {hasMainOutput ? <ToolResultFrame tool={primaryResult.provider || mainEntry?.tool} title={primaryResult.title || results.title || "Main output"} synthetic={mainEntry?.synthetic} onExpand={() => openTool("main")}>
          <MainToolOutput entry={mainEntry} result={primaryResult} results={results} activity={activity} backendRunId={backendRunId} />
        </ToolResultFrame> : <ResultPreview result={primaryResult} results={results} />}
      </PrimaryResult>}

      {!nativeResult && receipts.length > 0 && <section aria-label="Supporting workflow actions" className="mb-6">
        <h3 className="mb-3 text-sm font-semibold">What happened</h3>
        <div className="space-y-2">
          {receipts.map((receipt) => <div key={receipt.key} className="flex flex-wrap items-center gap-3 rounded-xl border border-white/10 bg-card/40 p-4">
            <Activity className="h-5 w-5 shrink-0 text-primary" />
            <div className="min-w-0 flex-1"><p className="text-sm font-medium">{receipt.title}</p>
            <p className="mt-1 text-xs text-muted-foreground">{toolResultName(receipt.tool)}</p>
            {receipt.preview?.length > 0 && <div className="mt-3 space-y-2 border-t border-white/10 pt-3">
              {receipt.preview.map((audience, index) => <div key={index} className="flex items-start justify-between gap-3 text-xs">
                <span className="break-words">{audience.name}</span>
                {audience.contacts !== null && <span className="shrink-0 text-muted-foreground">{audience.contacts.toLocaleString("en-US")} contacts</span>}
              </div>)}
            </div>}
            </div>
            <div className="flex flex-wrap gap-2">
              {receipt.actionId && <button type="button" aria-label={`View action: ${receipt.title}`} onClick={() => openTool(receipt.actionId)} className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-3 py-1.5 text-xs text-primary hover:bg-primary/10">View action</button>}
              {receipt.link && <a href={receipt.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-full border border-primary/25 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10">{receipt.linkLabel || `Open ${receipt.tool}`}<ExternalLink className="h-3 w-3" /></a>}
            </div>
          </div>)}
        </div>
      </section>}

      {!nativeAudit && primaryResult.kind !== "website_content" && <ResultsByTool entries={toolEntries} onOpen={openTool} />}

      {creatorsOutcome && <CreatorApprovalList items={creatorsOutcome.items} />}
      {!isFailure && (nextSteps.length > 0 || results.suggestionsLoading) && <section className="mb-6" aria-live="polite">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><ArrowRight className="h-4 w-4 text-primary" />Suggested next</h3>
        {nextSteps.length > 0
          ? <div className="flex flex-wrap gap-2">{nextSteps.map((step, index) => <button key={index} type="button" onClick={() => onStartWorkflow(step)} className="rounded-full border border-primary/25 bg-primary/[0.05] px-4 py-2 text-xs text-primary hover:bg-primary/10">{step}</button>)}</div>
          : <p className="text-sm text-muted-foreground">{results.suggestionsLoading ? "Finding useful follow-ups…" : "No follow-up suggestions are available for this result."}</p>}
      </section>}
      <section className="rounded-xl border border-white/10 bg-card/20 p-4 sm:p-5">
        <h3 className="text-sm font-semibold">Continue this workflow</h3>
        <p className="mt-1 text-sm text-muted-foreground">{approvedWeekly ? "This review uses fixed reporting dates and individually labelled source inputs. Start a new review with fresh inputs for the next week." : isFailure ? "Your completed work is saved. Try again or start a new workflow." : "Continue from this result or create something new."}</p>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <button type="button" onClick={() => { if (approvedWeekly) { setSearchParams({ weekly: "1" }); onNewWorkflow(); } else onStartWorkflow(prompt); }} className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium hover:bg-white/10"><RefreshCw className="h-4 w-4" />{approvedWeekly ? "New review with fresh exports" : "Run again"}</button>
          {!isFailure && !approvedWeekly && backendRunId && <button type="button" onClick={() => setShowSchedule(true)} className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium hover:bg-white/10"><CalendarClock className="h-4 w-4" />Schedule</button>}
          <button type="button" onClick={onNewWorkflow} className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium hover:bg-white/10"><Plus className="h-4 w-4" />New workflow</button>
        </div>
      </section>

      <div className="mt-5 flex flex-wrap items-center gap-5 border-t border-white/10 pt-5 text-xs text-muted-foreground">
        {backendRunId && <Link to={`/runs/${encodeURIComponent(backendRunId)}`} className="inline-flex items-center gap-1.5 hover:text-foreground"><ExternalLink className="h-3 w-3" />Open saved results</Link>}
        {activity?.length > 0 && <details className="group relative"><summary className="flex cursor-pointer list-none items-center gap-1.5 hover:text-foreground [&::-webkit-details-marker]:hidden"><Activity className="h-4 w-4" />Activity<ChevronDown className="h-3 w-3 group-open:rotate-180" /></summary><ol className="absolute bottom-full left-0 z-10 mb-2 max-h-56 w-72 overflow-y-auto rounded-xl border border-white/10 bg-[#121725] p-3 shadow-xl">{activity.map((step, index) => <li key={step.id || index} className="flex items-start gap-2 py-1.5 text-xs">{step.status === "completed" ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" /> : ["failed", "blocked"].includes(step.status) ? <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber-400" /> : <Clock className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />}<span>{step.action || step.tool || "Completed"}</span></li>)}</ol></details>}
        <button type="button" onClick={handleShare} className="inline-flex items-center gap-1.5 hover:text-foreground">{copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Share2 className="h-4 w-4" />}{copied ? "Copied" : "Share"}</button>
        {primaryResult.downloadUrl
          ? <a href={primaryResult.downloadUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 hover:text-foreground"><FileDown className="h-4 w-4" />Download result</a>
          : <button type="button" onClick={handleDownload} className="inline-flex items-center gap-1.5 hover:text-foreground"><FileDown className="h-4 w-4" />Download {primaryResult.preview?.body ? "output" : "summary"}</button>}
        {!isFailure && !backendRunId && <button type="button" onClick={() => setShowModal(true)} className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 font-semibold text-white"><Zap className="h-4 w-4" />Connect & run for real</button>}
      </div>
      {!backendRunId && <AccessRequestModal open={showModal} onClose={() => setShowModal(false)} workflowPrompt={workflowPrompt} />}
      <ScheduleModal open={showSchedule} onClose={() => setShowSchedule(false)} title={scheduleTitle || results.title} backendRunId={backendRunId} historyWorkflowId={historyWorkflowId} />
      <ToolResultDialog request={toolView} onClose={() => setToolView(null)} entries={toolEntries} primary={primaryResult} mainEntry={mainEntry} hasMainOutput={hasMainOutput} results={results} activity={activity || []} backendRunId={backendRunId} />
    </motion.div>
  );
}
