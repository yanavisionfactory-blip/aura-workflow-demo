import RunSupportAccess from "./RunSupportAccess";
import { useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { Activity, ArrowRight, BarChart3, CalendarClock, Check, ChevronDown, ExternalLink, FileDown, Plus, RefreshCw, Share2, Zap } from "lucide-react";
import AccessRequestModal from "./AccessRequestModal";
import ScheduleModal from "./ScheduleModal";
import CreatorApprovalList from "./CreatorApprovalList";
import ResultPreview from "./ResultPreview";
import ToolResultDialog, { MainToolOutput, ResultsByTool, ToolResultFrame, ToolOutputCards } from "./ToolResultView";
import { ResultsHeading, ResultsMetrics } from "./ResultsSummary";
import { buildSummaryText } from "@/lib/auraSummary";
import { resultMetrics, selectPrimaryOutcome, supportingReceipts, visualResultChoices } from "@/lib/resultPresentation.mjs";
import { mainToolEntry, preferredToolOutcome, supportingToolOutputs, toolResultEntries, toolResultName } from "@/lib/toolResultViews.mjs";
import { sheetWorkflowSummary } from "@/lib/workflowResultSummary.mjs";
import { campaignRepeatPrompt } from "@/lib/runtimePlan.mjs";
import { resultRevisionPrompt } from "@/lib/frameioResult.mjs";
import WorkflowOutcomeList from "./WorkflowOutcomeList";
import WorkflowToolResults from "./WorkflowToolResults";

const outlineButton = "inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium transition hover:bg-white/10";
const footerButton = "inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 hover:bg-white/5";

export default function ResultsView({ results, onNewWorkflow, onStartWorkflow, workflowPrompt, activity, prompt, interpretation, backendRunId, historyWorkflowId, scheduleTitle, onOpenRun }) {
  const isFailure = results.status === "failed" || results.status === "needs_attention";
  const [showModal, setShowModal] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showSchedule, setShowSchedule] = useState(false);
  const [toolView, setToolView] = useState(null);
  const dropdowns = useRef(new Map());
  const [searchParams, setSearchParams] = useSearchParams();
  const visualChoices = useMemo(() => visualResultChoices(activity || [], { title: results.title, summary: results.summary }), [activity, results]);
  const selectedVisual = visualChoices.find((choice) => choice.key === searchParams.get("main"));
  const primaryResult = selectedVisual?.result || preferredToolOutcome(selectPrimaryOutcome(results), activity || []);
  const toolEntries = useMemo(() => toolResultEntries(activity || []), [activity]);
  const mainEntry = useMemo(() => mainToolEntry(toolEntries, primaryResult, results.resultPresentation), [toolEntries, primaryResult, results.resultPresentation]);
  const outputEntry = mainEntry;
  const displayedResult = primaryResult;
  const supportingOutputs = supportingToolOutputs(toolEntries, primaryResult, results.resultPresentation).flatMap((group) => group.entries);
  const hasMainOutput = Boolean((primaryResult.kind && primaryResult.kind !== "result") || primaryResult.provider || mainEntry?.hasResponse || results.breakdown || primaryResult.items?.length);
  const nativeAudit = primaryResult.kind === "seo_audit";
  const approvedWeekly = primaryResult.kind === "weekly_review" && (primaryResult.packet?.version === 2 || primaryResult.packet?.provenance === "approved_export");
  const nativeResult = nativeAudit || ["weekly_review", "executive_review", "website_content", "marketing_tools"].includes(primaryResult.kind);
  const summaryFirst = !nativeResult && primaryResult.kind !== "frameio_review";
  const openTool = (id) => {
    const tool = id === "main" ? mainEntry?.tool || toolResultName(primaryResult.provider) : toolEntries.find((entry) => entry.id === id)?.tool;
    const dropdown = summaryFirst && dropdowns.current.get(tool);
    if (dropdown) {
      if (id === "main" || tool === (mainEntry?.tool || toolResultName(primaryResult.provider))) { dropdown.closest("article")?.scrollIntoView({ block: "start" }); return; }
      dropdown.open = true;
      dropdown.querySelector("summary")?.focus({ preventScroll: true });
      dropdown.scrollIntoView({ block: "nearest" });
    } else setToolView({ id });
  };
  const MainResultContainer = summaryFirst ? "details" : "section";
  const MainResultHeading = summaryFirst ? "summary" : "div";
  const sheetSummary = useMemo(() => sheetWorkflowSummary(toolEntries, primaryResult), [toolEntries, primaryResult]);
  const metrics = useMemo(() => sheetSummary?.metrics.length ? sheetSummary.metrics : isFailure ? [] : resultMetrics(results.metrics || [], activity || []), [results.metrics, activity, isFailure, sheetSummary]);
  const receipts = useMemo(() => supportingReceipts(results, activity || [], primaryResult, results.resultPresentation, mainEntry?.id), [activity, primaryResult, results, mainEntry]);
  const actions = sheetSummary?.actions.length ? [...sheetSummary.actions] : [
    ...(hasMainOutput ? [{ key: "primary", title: mainEntry?.action || primaryResult.title || "Workflow output saved", detail: mainEntry?.tool || toolResultName(primaryResult.provider), actionId: "main", actionLabel: "View result", icon: "report", link: primaryResult.link, linkLabel: primaryResult.linkLabel || `Open in ${mainEntry?.tool || toolResultName(primaryResult.provider)}` }] : []),
    ...receipts.map((receipt) => ({ ...receipt, detail: toolResultName(receipt.tool), actionLabel: "View action" })),
  ];
  for (const entry of toolEntries.filter((item) => ["failed", "blocked", "provider_error"].includes(item.status))) {
    if (!actions.some((action) => action.actionId === entry.id)) actions.push({ key: `issue-${entry.id}`, title: entry.action, detail: `${entry.tool} · Needs attention`, actionId: entry.id, actionLabel: "View issue", issue: true });
  }
  if (isFailure && !actions.some((action) => action.issue)) actions.push({ key: "final-review", title: toolEntries.length && toolEntries.every((entry) => entry.status === "completed") ? "Final review needs attention" : "Workflow needs attention", detail: "Your completed work is saved. AURA has not verified the full requested outcome.", issue: true, resume: Boolean(onOpenRun), actionId: onOpenRun ? null : "activity", actionLabel: "View issue" });
  const creatorsOutcome = (results.outcomes || []).find((outcome) => outcome.type === "creators" && outcome.items?.length > 0);
  const nextSteps = primaryResult.kind === "website_content" ? [
    "Review the changes to each page.",
    "Check image permissions and choose a reviewer.",
    "Prepare a developer handoff after the pages are approved.",
  ] : results.nextSteps || [];
  const savedSuggestions = isFailure && sheetSummary?.actions.length ? [
    { label: "Review the saved dashboard", open: () => openTool("main") },
    { label: "Review what still needs attention", open: onOpenRun || (() => openTool("activity")) },
  ] : [];
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
    const body = primaryResult.brief?.body || primaryResult.preview?.body;
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

  const resultSummary = <>
    <ResultsHeading centered={false} title={sheetSummary?.title ? `${sheetSummary.title}${isFailure ? " — review needed" : ""}` : primaryResult.completionTitle || results.title || "Workflow complete"} summary={sheetSummary?.summary || primaryResult.completionSummary || results.summary} isFailure={isFailure} />
    <ResultsMetrics metrics={metrics} compact />
  </>;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className={`mx-auto w-full pb-8 ${summaryFirst ? "max-w-5xl" : ["website_content", "spreadsheet", "frameio_review"].includes(primaryResult.kind) ? "max-w-6xl" : "max-w-5xl"}`}>
      {!nativeResult && !summaryFirst && resultSummary}
      {nativeResult && <ResultPreview result={primaryResult} results={results} activity={activity} backendRunId={backendRunId} />}
      {nativeResult && !nativeAudit && primaryResult.kind !== "website_content" && <ResultsByTool entries={toolEntries} onOpen={openTool} />}

      {!nativeResult && !summaryFirst && <MainResultContainer aria-label="Main workflow result" className="group mb-6">
        <MainResultHeading className="mb-4 flex cursor-pointer list-none flex-wrap items-center gap-2 text-sm font-semibold [&::-webkit-details-marker]:hidden"><BarChart3 className="h-4 w-4 text-violet-400" />Main result<span className="text-[11px] font-normal text-muted-foreground">— the actual output</span>{summaryFirst && <ChevronDown className="h-3.5 w-3.5 text-muted-foreground group-open:rotate-180" />}
          {summaryFirst && primaryResult.link && <a href={primaryResult.link} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()} className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-cyan-400/25 px-3 py-1.5 text-[11px] font-medium text-cyan-300 hover:bg-cyan-400/10"><ExternalLink className="h-3 w-3" />{primaryResult.linkLabel || `Open in ${mainEntry?.tool || toolResultName(primaryResult.provider)}`}</a>}
        </MainResultHeading>
        {!summaryFirst && <ResultsByTool entries={toolEntries} selectedTool={outputEntry?.tool || toolResultName(displayedResult.provider)} onOpen={openTool} />}
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

        {(primaryResult.link && !["spreadsheet", "frameio_review"].includes(primaryResult.kind) || primaryResult.artifact?.link) && <div className="flex flex-wrap gap-3">
          {primaryResult.link && !["spreadsheet", "frameio_review"].includes(primaryResult.kind) && <a href={primaryResult.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary/90"><ExternalLink className="h-4 w-4" />{primaryResult.linkLabel || "Open result"}</a>}
          {primaryResult.artifact?.link && <a href={primaryResult.artifact.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-primary/30 px-4 py-2.5 text-sm font-medium text-primary hover:bg-primary/10"><ExternalLink className="h-4 w-4" />{primaryResult.artifact.linkLabel || "Open presentation"}</a>}
        </div>}
        {displayedResult.kind === "frameio_review" ? <MainToolOutput entry={outputEntry} result={displayedResult} results={results} activity={activity} backendRunId={backendRunId} /> : hasMainOutput ? <ToolResultFrame tool={outputEntry?.tool || displayedResult.provider} backupNotice={outputEntry?.backupNotice} userEdited={outputEntry?.userEdited || displayedResult.userEdited} title={displayedResult.title || results.title || "Main output"} synthetic={outputEntry?.synthetic} appScreen={["spreadsheet", "ai_response"].includes(displayedResult.kind)} onExpand={summaryFirst ? undefined : () => openTool("main")} link={summaryFirst ? primaryResult.link : null}>
          <MainToolOutput entry={outputEntry} result={displayedResult} results={results} activity={activity} backendRunId={backendRunId} />
        </ToolResultFrame> : <ResultPreview result={primaryResult} results={results} />}
          {artifactDelivery && <p className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground"><span>Presentation · {primaryResult.artifact?.title || primaryResult.title}</span><span className="text-emerald-400">{artifactDelivery.artifactDelivered ? "Attached and delivered" : "Created in Canva"}</span></p>}
        </div>
      </MainResultContainer>}

      {summaryFirst && <section aria-label="Workflow summary" className="mt-7">
        {resultSummary}
        {visualChoices.length > 1 && <label className="mb-5 block text-xs text-muted-foreground">Main output<select value={visualChoices.find((choice) => choice.result.designId === primaryResult.designId)?.key || ""} onChange={(event) => { const next = new URLSearchParams(searchParams); next.set("main", event.target.value); setSearchParams(next); }} className="mt-2 block w-full rounded-xl border border-white/10 bg-card p-3 text-sm text-foreground">{visualChoices.map((choice) => <option key={choice.key} value={choice.key}>{choice.label}</option>)}</select></label>}
        <WorkflowToolResults entries={toolEntries} primary={primaryResult} mainEntry={mainEntry} hasMainOutput={hasMainOutput} results={results} activity={activity || []} backendRunId={backendRunId} actions={actions} dropdowns={dropdowns} onOpenRun={onOpenRun} onOpen={openTool} />
        <ResultsByTool entries={toolEntries} selectedTool={outputEntry?.tool || displayedResult.provider} onOpen={openTool} compact />
      </section>}

      {summaryFirst && <ToolResultDialog inline request={toolView} onClose={() => setToolView(null)} entries={toolEntries} primary={primaryResult} mainEntry={mainEntry} hasMainOutput={hasMainOutput} results={results} activity={activity || []} backendRunId={backendRunId} />}

      {!summaryFirst && supportingOutputs.length > 0 && <section aria-label="Supporting tool outputs" className="mb-7 space-y-4">
        <h2 className="text-sm font-semibold">More outputs from this workflow</h2>
        <ToolOutputCards entries={supportingOutputs} activity={activity} backendRunId={backendRunId} onOpen={openTool} />
      </section>}

      {!nativeResult && !summaryFirst && <WorkflowOutcomeList actions={actions} onOpen={openTool} onOpenRun={onOpenRun} />}

      {creatorsOutcome && <CreatorApprovalList items={creatorsOutcome.items} />}
      {(savedSuggestions.length > 0 || !isFailure && (nextSteps.length > 0 || results.suggestionsLoading)) && <section className="mb-6" aria-live="polite">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><ArrowRight className="h-4 w-4 text-primary" />Suggested next</h3>
        {savedSuggestions.length > 0 ? <div className="flex flex-wrap gap-2">{savedSuggestions.map((item) => <button key={item.label} type="button" onClick={item.open} className="rounded-full border border-violet-400/20 px-3 py-1.5 text-xs text-violet-400 hover:bg-violet-400/10">{item.label}</button>)}</div> : nextSteps.length > 0
          ? <div className="flex flex-wrap gap-2">{nextSteps.map((step, index) => <button key={index} type="button" onClick={() => onStartWorkflow(primaryResult.kind === "frameio_review" ? resultRevisionPrompt({ instruction: step, result: primaryResult }) : step)} className="rounded-full border border-violet-400/20 px-3 py-1.5 text-xs text-violet-400 hover:bg-violet-400/10">{step}</button>)}</div>
          : <p className="text-sm text-muted-foreground">{results.suggestionsLoading ? "Finding useful follow-ups…" : "No follow-up suggestions are available for this result."}</p>}
      </section>}
      {!results.collection && <section className="rounded-2xl border border-violet-400/15 bg-violet-400/[0.035] p-4">
        <h3 className="text-sm font-semibold">What would you like to do next?</h3>
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{approvedWeekly ? "This review uses fixed reporting dates and individually labelled source inputs. Start a new review with fresh inputs for the next week." : isFailure ? "Your completed work is saved. Try again or start a new workflow." : "Run it again, automate it for later, or start something new."}</p>
        <div className={`mt-3 grid gap-2 ${!isFailure && !approvedWeekly && backendRunId ? "sm:grid-cols-3" : "sm:grid-cols-2"}`}>
          <button type="button" onClick={() => { if (approvedWeekly) { setSearchParams({ weekly: "1" }); onNewWorkflow(); } else onStartWorkflow(campaignRepeatPrompt(prompt, activity) || prompt); }} className={outlineButton}><RefreshCw className="h-4 w-4" />{approvedWeekly ? "New review with fresh exports" : "Run again"}</button>
          {!isFailure && !approvedWeekly && backendRunId && <button type="button" onClick={() => setShowSchedule(true)} className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-500 to-sky-400 px-4 py-2.5 text-sm font-semibold text-white shadow-[0_5px_20px_rgba(139,92,246,0.15)]"><CalendarClock className="h-4 w-4" />Schedule</button>}
          <button type="button" onClick={onNewWorkflow} className={outlineButton}><Plus className="h-4 w-4" />New workflow</button>
        </div>
      </section>}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/10 pt-4 text-xs">
        <Link to="/results/collect" className={footerButton}>Collect saved results</Link>
        {activity?.length > 0 && <button type="button" onClick={() => openTool("activity")} className={footerButton}><Activity className="h-3.5 w-3.5" />Activity</button>}
        <button type="button" onClick={handleShare} className={footerButton}>{copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Share2 className="h-3.5 w-3.5" />}{copied ? "Copied" : "Copy summary"}</button>
        {primaryResult.downloadUrl
          ? <a href={primaryResult.downloadUrl} target="_blank" rel="noopener noreferrer" className={footerButton}><FileDown className="h-3.5 w-3.5" />Download</a>
          : <button type="button" onClick={handleDownload} className={footerButton}><FileDown className="h-3.5 w-3.5" />{primaryResult.kind === "frameio_review" ? "Download original brief" : "Download summary"}</button>}
        {!isFailure && !backendRunId && !results.collection && <button type="button" onClick={() => setShowModal(true)} className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 font-semibold text-white"><Zap className="h-4 w-4" />Connect & run for real</button>}
      </div>
      {!backendRunId && !results.collection && <AccessRequestModal open={showModal} onClose={() => setShowModal(false)} workflowPrompt={workflowPrompt} />}
      <RunSupportAccess runId={backendRunId} compact />
      <ScheduleModal open={showSchedule} onClose={() => setShowSchedule(false)} title={scheduleTitle || results.title} backendRunId={backendRunId} historyWorkflowId={historyWorkflowId} />
      {!summaryFirst && <ToolResultDialog request={toolView} onClose={() => setToolView(null)} entries={toolEntries} primary={primaryResult} mainEntry={mainEntry} hasMainOutput={hasMainOutput} results={results} activity={activity || []} backendRunId={backendRunId} />}
    </motion.div>
  );
}
