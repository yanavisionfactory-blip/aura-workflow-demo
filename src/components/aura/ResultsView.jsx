import RunSupportAccess from "./RunSupportAccess";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, ArrowRight, BarChart3, CalendarClock, Check, ChevronDown, ExternalLink, FileDown, FileText, Plus, RefreshCw, Share2, Table2, Zap } from "lucide-react";
import AccessRequestModal from "./AccessRequestModal";
import ScheduleModal from "./ScheduleModal";
import CreatorApprovalList from "./CreatorApprovalList";
import ResultPreview from "./ResultPreview";
import ToolResultDialog, { MainToolOutput, ResultsByTool, ToolResultFrame } from "./ToolResultView";
import { ResultsHeading, ResultsMetrics } from "./ResultsSummary";
import { buildSummaryText } from "@/lib/auraSummary";
import { resultMetrics, selectPrimaryOutcome, supportingReceipts, visualResultChoices } from "@/lib/resultPresentation.mjs";
import { mainToolEntry, toolResultEntries, toolResultName } from "@/lib/toolResultViews.mjs";
import { sheetWorkflowSummary } from "@/lib/workflowResultSummary.mjs";
import { campaignRepeatPrompt } from "@/lib/runtimePlan.mjs";

const smallButton = "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-full border border-cyan-400/25 px-3 py-1.5 text-[11px] font-medium text-cyan-300 transition hover:bg-cyan-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300";
const outlineButton = "inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium transition hover:bg-white/10";
const footerButton = "inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 hover:bg-white/5";

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
  const MainResultContainer = primaryResult.kind === "spreadsheet" ? "section" : "details";
  const MainResultHeading = primaryResult.kind === "spreadsheet" ? "div" : "summary";
  const nativeAudit = primaryResult.kind === "seo_audit";
  const approvedWeekly = primaryResult.kind === "weekly_review" && (primaryResult.packet?.version === 2 || primaryResult.packet?.provenance === "approved_export");
  const nativeResult = nativeAudit || ["weekly_review", "executive_review", "website_content", "marketing_tools"].includes(primaryResult.kind);
  const sheetSummary = useMemo(() => sheetWorkflowSummary(toolEntries, primaryResult), [toolEntries, primaryResult]);
  const metrics = useMemo(() => isFailure ? [] : sheetSummary?.metrics.length ? sheetSummary.metrics : resultMetrics(results.metrics || [], activity || []), [results.metrics, activity, isFailure, sheetSummary]);
  const receipts = useMemo(() => supportingReceipts(results, activity || [], primaryResult, results.resultPresentation, mainEntry?.id), [activity, primaryResult, results, mainEntry]);
  const actions = sheetSummary?.actions.length ? [...sheetSummary.actions] : [
    ...(hasMainOutput ? [{ key: "primary", title: mainEntry?.action || primaryResult.title || "Workflow output saved", detail: toolResultName(primaryResult.provider || mainEntry?.tool), actionId: "main", actionLabel: "View result", icon: "report" }] : []),
    ...receipts.map((receipt) => ({ ...receipt, detail: toolResultName(receipt.tool), actionLabel: "View action" })),
  ];
  for (const entry of toolEntries.filter((item) => ["failed", "blocked", "provider_error"].includes(item.status))) {
    if (!actions.some((action) => action.actionId === entry.id)) actions.push({ key: `issue-${entry.id}`, title: entry.action, detail: `${entry.tool} · Needs attention`, actionId: entry.id, actionLabel: "View issue", issue: true });
  }
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

  if (primaryResult.kind === "marketing_tools") return <div className="mx-auto w-full max-w-3xl pb-8"><ResultPreview result={primaryResult} results={results} activity={activity} backendRunId={backendRunId} /></div>;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className={`mx-auto w-full pb-8 ${["website_content", "spreadsheet"].includes(primaryResult.kind) ? "max-w-6xl" : "max-w-3xl"}`}>
      {!nativeResult && <ResultsHeading centered title={(!isFailure && sheetSummary?.title) || results.title || "Workflow complete"} summary={(!isFailure && sheetSummary?.summary) || results.summary} isFailure={isFailure} />}
      {!nativeResult && <ResultsMetrics metrics={metrics} compact />}

      {nativeResult && <ResultPreview result={primaryResult} results={results} activity={activity} backendRunId={backendRunId} />}

      {!nativeResult && <MainResultContainer aria-label="Main workflow result" className="group mb-6">
        <MainResultHeading className={`flex w-fit list-none items-center gap-2 text-sm font-semibold [&::-webkit-details-marker]:hidden ${primaryResult.kind === "spreadsheet" ? "" : "cursor-pointer"}`}><BarChart3 className="h-4 w-4 text-violet-400" />Results<span className="text-[11px] font-normal text-muted-foreground">— the actual output</span>{primaryResult.kind !== "spreadsheet" && <ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition group-open:rotate-180" />}</MainResultHeading>
        <div className="mt-4 space-y-4">

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

        {(primaryResult.link && primaryResult.kind !== "spreadsheet" || primaryResult.artifact?.link) && <div className="flex flex-wrap gap-3">
          {primaryResult.link && primaryResult.kind !== "spreadsheet" && <a href={primaryResult.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary/90"><ExternalLink className="h-4 w-4" />{primaryResult.linkLabel || "Open result"}</a>}
          {primaryResult.artifact?.link && <a href={primaryResult.artifact.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-primary/30 px-4 py-2.5 text-sm font-medium text-primary hover:bg-primary/10"><ExternalLink className="h-4 w-4" />{primaryResult.artifact.linkLabel || "Open presentation"}</a>}
        </div>}
        {hasMainOutput ? <ToolResultFrame tool={primaryResult.provider || mainEntry?.tool} title={primaryResult.title || results.title || "Main output"} synthetic={mainEntry?.synthetic} appScreen={primaryResult.kind === "spreadsheet"} onExpand={() => openTool("main")}>
          <MainToolOutput entry={mainEntry} result={primaryResult} results={results} activity={activity} backendRunId={backendRunId} />
        </ToolResultFrame> : <ResultPreview result={primaryResult} results={results} />}
          {artifactDelivery && <p className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground"><span>Presentation · {primaryResult.artifact?.title || primaryResult.title}</span><span className="text-emerald-400">{artifactDelivery.artifactDelivered ? "Attached and delivered" : "Created in Canva"}</span></p>}
        </div>
      </MainResultContainer>}

      {!nativeResult && actions.length > 0 && <section aria-label="Supporting workflow actions" className="mb-6">
        <h3 className="mb-3 text-sm font-semibold">What happened</h3>
        <div className="space-y-2">
          {actions.map((action) => {
            const Icon = action.issue ? AlertTriangle : action.icon === "sources" ? BarChart3 : action.icon === "sheet" ? Table2 : FileText;
            return <div key={action.key} className={`flex flex-wrap items-center gap-3 rounded-xl border px-3 py-3 sm:flex-nowrap ${action.issue ? "border-amber-400/30 bg-amber-400/[0.04]" : "border-white/10 bg-[#0c121e]/65"}`}>
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-xl ${action.issue ? "bg-amber-400/10 text-amber-400" : "bg-violet-400/10 text-violet-400"}`}><Icon className="h-4 w-4" /></span>
              <div className="min-w-0 flex-1"><p className="text-sm font-medium">{action.count !== undefined && <strong className="mr-1.5 text-lg font-bold">{action.count}</strong>}{action.title}</p>
                <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">{action.detail}</p>
                {action.preview?.length > 0 && <div className="mt-2 space-y-1 text-xs text-muted-foreground">{action.preview.map((audience, index) => <p key={index}>{audience.name}{audience.contacts !== null && ` · ${audience.contacts.toLocaleString("en-US")} contacts`}</p>)}</div>}
              </div>
              <div className="flex flex-wrap gap-2">
                {action.actionId && <button type="button" aria-label={`${action.actionLabel}: ${action.title}`} onClick={() => openTool(action.actionId)} className={`${smallButton} ${action.issue ? "border-amber-400/30 text-amber-300 hover:bg-amber-400/10" : ""}`}>{action.actionLabel}</button>}
                {action.link && <a href={action.link} target="_blank" rel="noopener noreferrer" className={smallButton}><ExternalLink className="h-3 w-3" />{action.linkLabel || `Open ${action.tool}`}</a>}
              </div>
            </div>;
          })}
        </div>
      </section>}

      {!nativeAudit && primaryResult.kind !== "website_content" && <ResultsByTool entries={toolEntries} onOpen={openTool} />}


      {creatorsOutcome && <CreatorApprovalList items={creatorsOutcome.items} />}
      {!isFailure && (nextSteps.length > 0 || results.suggestionsLoading) && <section className="mb-6" aria-live="polite">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><ArrowRight className="h-4 w-4 text-primary" />Suggested next</h3>
        {nextSteps.length > 0
          ? <div className="flex flex-wrap gap-2">{nextSteps.map((step, index) => <button key={index} type="button" onClick={() => onStartWorkflow(step)} className="rounded-full border border-violet-400/20 px-3 py-1.5 text-xs text-violet-400 hover:bg-violet-400/10">{step}</button>)}</div>
          : <p className="text-sm text-muted-foreground">{results.suggestionsLoading ? "Finding useful follow-ups…" : "No follow-up suggestions are available for this result."}</p>}
      </section>}
      <section className="rounded-2xl border border-violet-400/15 bg-violet-400/[0.035] p-4">
        <h3 className="text-sm font-semibold">What would you like to do next?</h3>
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{approvedWeekly ? "This review uses fixed reporting dates and individually labelled source inputs. Start a new review with fresh inputs for the next week." : isFailure ? "Your completed work is saved. Try again or start a new workflow." : "Run it again, automate it for later, or start something new."}</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <button type="button" onClick={() => { if (approvedWeekly) { setSearchParams({ weekly: "1" }); onNewWorkflow(); } else onStartWorkflow(campaignRepeatPrompt(prompt, activity) || prompt); }} className={outlineButton}><RefreshCw className="h-4 w-4" />{approvedWeekly ? "New review with fresh exports" : "Run again"}</button>
          {!isFailure && !approvedWeekly && backendRunId && <button type="button" onClick={() => setShowSchedule(true)} className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-500 to-sky-400 px-4 py-2.5 text-sm font-semibold text-white shadow-[0_5px_20px_rgba(139,92,246,0.15)]"><CalendarClock className="h-4 w-4" />Schedule</button>}
          <button type="button" onClick={onNewWorkflow} className={outlineButton}><Plus className="h-4 w-4" />New workflow</button>
        </div>
      </section>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/10 pt-4 text-xs">
        {activity?.length > 0 && <button type="button" onClick={() => openTool("activity")} className={footerButton}><Activity className="h-3.5 w-3.5" />Activity</button>}
        <button type="button" onClick={handleShare} className={footerButton}>{copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Share2 className="h-3.5 w-3.5" />}{copied ? "Copied" : "Share"}</button>
        {primaryResult.downloadUrl
          ? <a href={primaryResult.downloadUrl} target="_blank" rel="noopener noreferrer" className={footerButton}><FileDown className="h-3.5 w-3.5" />Download</a>
          : <button type="button" onClick={handleDownload} className={footerButton}><FileDown className="h-3.5 w-3.5" />Download</button>}
        {!isFailure && !backendRunId && <button type="button" onClick={() => setShowModal(true)} className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 font-semibold text-white"><Zap className="h-4 w-4" />Connect & run for real</button>}
      </div>
      {!backendRunId && <AccessRequestModal open={showModal} onClose={() => setShowModal(false)} workflowPrompt={workflowPrompt} />}
      <RunSupportAccess runId={backendRunId} compact />
      <ScheduleModal open={showSchedule} onClose={() => setShowSchedule(false)} title={scheduleTitle || results.title} backendRunId={backendRunId} historyWorkflowId={historyWorkflowId} />
      <ToolResultDialog request={toolView} onClose={() => setToolView(null)} entries={toolEntries} primary={primaryResult} mainEntry={mainEntry} hasMainOutput={hasMainOutput} results={results} activity={activity || []} backendRunId={backendRunId} />
    </motion.div>
  );
}
