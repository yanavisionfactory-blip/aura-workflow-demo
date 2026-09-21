import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  Check,
  CheckCircle2,
  ExternalLink,
  FileDown,
  FileText,
  MailCheck,
  Plus,
  Presentation,
  RefreshCw,
  Share2,
  Zap,
} from "lucide-react";
import AccessRequestModal from "./AccessRequestModal";
import BreakdownTable from "./BreakdownTable";
import ScheduleModal from "./ScheduleModal";
import CreatorApprovalList from "./CreatorApprovalList";
import ResultContent from "./ResultContent";
import { buildSummaryText } from "@/lib/auraSummary";
import { resultArtifacts, resultKpis, selectPrimaryOutcome } from "@/lib/resultPresentation.mjs";

export default function ResultsView({
  results,
  onNewWorkflow,
  onStartWorkflow,
  workflowPrompt,
  activity,
  prompt,
  interpretation,
  backendRunId,
  historyWorkflowId,
  scheduleTitle,
}) {
  const isFailure = results.status === "failed" || results.status === "needs_attention";
  const [showModal, setShowModal] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showSchedule, setShowSchedule] = useState(false);

  const primaryResult = useMemo(() => selectPrimaryOutcome(results), [results]);
  const artifacts = useMemo(
    () => resultArtifacts(activity || [], primaryResult),
    [activity, primaryResult]
  );
  const metrics = useMemo(
    () => resultKpis(results.metrics || [], activity || [], artifacts, results.status),
    [activity, artifacts, results.metrics, results.status]
  );
  const toolsUsed = useMemo(() => {
    const grouped = new Map();
    for (const step of (activity || []).filter((item) => item.status === "completed")) {
      const tool = step.tool || "AURA";
      const current = grouped.get(tool) || { key: tool, tool, count: 0, actions: [] };
      current.count += 1;
      current.actions.push(step.action || "Completed tool action");
      grouped.set(tool, current);
    }
    return [...grouped.values()];
  }, [activity]);
  const creatorsOutcome = (results.outcomes || []).find((outcome) =>
    outcome.type === "creators" && outcome.items?.length > 0
  );
  const nextSteps = results.nextSteps || [];

  const summaryArgs = {
    title: results.title,
    summary: results.summary,
    metrics,
    outcomes: results.outcomes,
    activity,
    prompt,
    interpretation,
    nextSteps,
  };

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
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full max-w-5xl mx-auto">
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: "spring", stiffness: 200, damping: 20 }}
        className="mb-5 flex flex-col items-center text-center"
      >
        <div className={`inline-flex p-3 rounded-2xl border mb-4 ${isFailure ? "bg-amber-400/10 border-amber-400/20" : "bg-emerald-400/10 border-emerald-400/20 glow-success"}`}>
          {isFailure
            ? <AlertTriangle className="w-8 h-8 text-amber-400" />
            : <CheckCircle2 className="w-8 h-8 text-emerald-400" />}
        </div>
        <h2 className="text-2xl font-bold mb-1">{results.title || "Workflow complete"}</h2>
        <p className="text-sm text-muted-foreground max-w-xl mx-auto">{results.summary}</p>
      </motion.div>

      <motion.section
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="mb-5"
      >
        <div className="mb-2.5 flex items-end justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">Result snapshot</p>
            <h3 className="mt-1 text-sm font-medium">Key outcomes</h3>
          </div>
          <span className="text-[10px] text-muted-foreground/65">Verified from this run</span>
        </div>
        <div className={`grid gap-3 ${metrics.length > 1 ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-1"}`}>
          {metrics.map((metric, index) => (
            <div key={`${metric.label}:${index}`} className="relative overflow-hidden rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/[0.09] via-card/55 to-card/35 px-4 py-4">
              <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/50 to-transparent" />
              <div className="truncate text-2xl font-bold tracking-tight text-foreground">{metric.value}</div>
              <div className="mt-1 text-xs text-muted-foreground">{metric.label}</div>
            </div>
          ))}
        </div>
      </motion.section>

      <motion.section
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.18 }}
        className="mb-5 overflow-hidden rounded-2xl border border-primary/20 bg-gradient-to-br from-primary/[0.08] via-card/60 to-card/30 shadow-lg shadow-primary/[0.04]"
      >
        <div className="flex flex-col gap-5 p-5 sm:p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 flex-1">
              <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-primary">
                <FileText className="h-4 w-4" />
                Your result
              </div>
              <h3 className="text-lg font-semibold leading-snug">{primaryResult.title || results.title || "Workflow result"}</h3>
              {primaryResult.provider && (
                <span className="mt-2 inline-flex rounded-full border border-white/[0.08] bg-white/[0.04] px-2.5 py-1 text-[11px] text-muted-foreground">
                  {primaryResult.providerVerb || "Created in"} {primaryResult.provider}
                </span>
              )}
              {primaryResult.kind === "email" ? (
                <div className="mt-4 overflow-hidden rounded-xl border border-white/[0.07] bg-[#090f1e]/45">
                  <div className="flex items-center gap-2 border-b border-white/[0.06] px-3.5 py-3 text-xs font-medium">
                    <MailCheck className="h-4 w-4 text-primary" /> Sent email
                  </div>
                  <div className="space-y-2 px-3.5 py-3 text-xs">
                    {primaryResult.recipient && (
                      <p><span className="text-muted-foreground">To:</span> {primaryResult.recipient}</p>
                    )}
                    {primaryResult.subject && (
                      <p><span className="text-muted-foreground">Subject:</span> {primaryResult.subject}</p>
                    )}
                    <p className="whitespace-pre-line border-t border-white/[0.06] pt-2.5 leading-relaxed text-muted-foreground">
                      {primaryResult.body || primaryResult.detail || results.summary}
                    </p>
                  </div>
                </div>
              ) : (
                <>
                  <p className="mt-4 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60">Result</p>
                  <div className="mt-2 rounded-xl border border-white/[0.07] bg-[#090f1e]/45 p-4">
                    <ResultContent content={primaryResult.detail || results.summary} />
                  </div>
                </>
              )}
            </div>

            <div className="flex shrink-0 flex-wrap gap-2 sm:max-w-[15rem] sm:justify-end">
              {primaryResult.link && (
                <a
                  href={primaryResult.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-primary to-accent px-3.5 py-2 text-xs font-semibold text-white shadow-lg shadow-primary/20"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  {primaryResult.linkLabel || "Open result"}
                </a>
              )}
              {primaryResult.artifact?.link && (
                <a
                  href={primaryResult.artifact.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-xl border border-primary/25 bg-primary/[0.06] px-3.5 py-2 text-xs font-medium text-primary hover:bg-primary/[0.12]"
                >
                  <Presentation className="h-3.5 w-3.5" />
                  {primaryResult.artifact.linkLabel || "View presentation"}
                </a>
              )}
              {primaryResult.downloadUrl ? (
                <a
                  href={primaryResult.downloadUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2 text-xs font-medium hover:bg-white/[0.08]"
                >
                  <FileDown className="h-3.5 w-3.5" /> Download
                </a>
              ) : (
                <button
                  type="button"
                  onClick={handleDownload}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2 text-xs font-medium hover:bg-white/[0.08]"
                >
                  <FileDown className="h-3.5 w-3.5" /> Download summary
                </button>
              )}
              <button
                type="button"
                onClick={handleShare}
                className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2 text-xs font-medium hover:bg-white/[0.08]"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Share2 className="h-3.5 w-3.5" />}
                {copied ? "Copied" : "Share"}
              </button>
            </div>
          </div>

          {results.breakdown ? (
            <div className="overflow-hidden rounded-xl border border-white/[0.06] bg-[#090f1e]/55">
              <BreakdownTable breakdown={results.breakdown} />
            </div>
          ) : primaryResult.items?.length > 0 ? (
            <div className="grid gap-2 border-t border-white/[0.06] pt-4 sm:grid-cols-2">
              {primaryResult.items.slice(0, 4).map((item, index) => (
                <div key={index} className="rounded-xl border border-white/[0.06] bg-[#090f1e]/45 px-3.5 py-3">
                  <p className="text-sm font-medium">{item.label}</p>
                  {item.detail && <p className="mt-1 text-xs text-muted-foreground">{item.detail}</p>}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </motion.section>

      {(artifacts.length > 0 || toolsUsed.length > 0) && (
        <motion.section
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.24 }}
          className="mb-5 rounded-2xl border border-white/[0.07] bg-card/30 p-5"
        >
          <div className="mb-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">Connected results</p>
            <h3 className="mt-1 text-sm font-medium">Results in your tools</h3>
            <p className="mt-1 text-[11px] text-muted-foreground">Open created work in the provider, or inspect the exact sources used for this result.</p>
          </div>
          {artifacts.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2">
              {artifacts.map((artifact) => (
                <div key={artifact.key} className="overflow-hidden rounded-xl border border-white/[0.07] bg-[#090f1e]/45">
                  {artifact.previewImage && (
                    <img src={artifact.previewImage} alt="" className="h-32 w-full border-b border-white/[0.06] object-cover" />
                  )}
                  <div className="flex min-h-[7rem] flex-col p-3.5">
                    <div className="flex items-start gap-2.5">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-400/10">
                        <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{artifact.provider}</p>
                          {artifact.isPrimary && <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[9px] font-medium text-primary">Primary</span>}
                        </div>
                        <p className="mt-1 line-clamp-2 text-sm font-medium leading-snug">{artifact.title}</p>
                        {artifact.detail && <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">{artifact.detail}</p>}
                      </div>
                    </div>
                    {artifact.link ? (
                      <a
                        href={artifact.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-3 inline-flex w-fit items-center gap-1.5 text-xs font-medium text-primary hover:underline"
                      >
                        {artifact.linkLabel}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : (
                      <span className="mt-3 text-[11px] font-medium text-emerald-400">Completed in {artifact.provider}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {toolsUsed.length > 0 && (
            <div className={`${artifacts.length ? "mt-4 border-t border-white/[0.06] pt-4" : ""}`}>
              <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">Tool actions completed</p>
              <div className="flex flex-wrap gap-2">
                {toolsUsed.map((item) => (
                  <span key={item.key} className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.035] px-2.5 py-1.5 text-[11px] text-foreground/75" title={item.actions.join(" · ")}>
                    <Check className="h-3 w-3 text-emerald-400" />
                    {item.tool}{item.count > 1 ? ` · ${item.count} actions` : ""}
                  </span>
                ))}
              </div>
            </div>
          )}
        </motion.section>
      )}

      {creatorsOutcome && <CreatorApprovalList items={creatorsOutcome.items} />}

      <motion.section
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="mb-4 rounded-2xl border border-primary/15 bg-primary/[0.04] p-5"
      >
        <h3 className="text-sm font-medium">What would you like to do next?</h3>
        <p className="mt-1 text-[11px] text-muted-foreground/70">
          {isFailure
            ? "AURA saved the completed work. Try again now or adjust the workflow."
            : "Continue from this result, automate it for later, or start something new."}
        </p>

        {!isFailure && nextSteps.length > 0 && (
          <div className="my-4 border-y border-white/[0.06] py-4">
            <p className="mb-2.5 flex items-center gap-2 text-xs font-medium text-foreground/90">
              <ArrowRight className="h-3.5 w-3.5 text-primary" /> Suggested next
            </p>
            <div className="flex flex-wrap gap-2">
              {nextSteps.map((step, index) => (
                <button
                  key={index}
                  type="button"
                  onClick={() => onStartWorkflow(step)}
                  className="rounded-full border border-primary/20 px-3 py-1.5 text-xs text-primary transition-colors hover:bg-primary/10"
                >
                  {step}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className={`mt-4 grid gap-2 ${isFailure ? "grid-cols-2" : "grid-cols-1 sm:grid-cols-3"}`}>
          <motion.button
            whileHover={{ scale: 1.01 }}
            whileTap={{ scale: 0.99 }}
            type="button"
            onClick={() => onStartWorkflow(prompt)}
            className="flex items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm font-medium transition-colors hover:bg-white/10"
          >
            <RefreshCw className="h-4 w-4" /> Run again
          </motion.button>
          {!isFailure && (
            <motion.button
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              type="button"
              onClick={() => setShowSchedule(true)}
              className="flex items-center justify-center gap-1.5 rounded-xl bg-gradient-to-r from-primary to-accent px-3 py-2.5 text-sm font-semibold text-white shadow-lg shadow-primary/20"
            >
              <CalendarClock className="h-4 w-4" /> Schedule
            </motion.button>
          )}
          <motion.button
            whileHover={{ scale: 1.01 }}
            whileTap={{ scale: 0.99 }}
            type="button"
            onClick={onNewWorkflow}
            className="flex items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm font-medium transition-colors hover:bg-white/10"
          >
            <Plus className="h-4 w-4" /> New workflow
          </motion.button>
        </div>
      </motion.section>

      {!isFailure && (
        <div className="flex justify-end border-t border-white/[0.06] pt-4">
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            type="button"
            onClick={() => setShowModal(true)}
            className="flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-primary to-accent px-3.5 py-2 text-xs font-semibold text-white shadow-lg shadow-primary/20"
          >
            <Zap className="h-3.5 w-3.5" /> Connect & run for real
          </motion.button>
        </div>
      )}

      <AccessRequestModal open={showModal} onClose={() => setShowModal(false)} workflowPrompt={workflowPrompt} />
      <ScheduleModal
        open={showSchedule}
        onClose={() => setShowSchedule(false)}
        title={scheduleTitle || results.title}
        backendRunId={backendRunId}
        historyWorkflowId={historyWorkflowId}
      />
    </motion.div>
  );
}
