import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  Check,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  FileDown,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  Share2,
  Zap,
} from "lucide-react";
import ProofLine from "./ProofLine";
import AccessRequestModal from "./AccessRequestModal";
import BreakdownTable from "./BreakdownTable";
import ScheduleModal from "./ScheduleModal";
import CreatorApprovalList from "./CreatorApprovalList";
import { buildSummaryText } from "@/lib/auraSummary";
import { meaningfulMetrics, selectPrimaryOutcome, supportingReceipts } from "@/lib/resultPresentation.mjs";

const statusStyle = {
  completed: { label: "Completed", dot: "bg-emerald-400", text: "text-emerald-400" },
  running: { label: "Running", dot: "bg-accent", text: "text-accent" },
  failed: { label: "Failed", dot: "bg-amber-400", text: "text-amber-400" },
  pending: { label: "Pending", dot: "bg-slate-500", text: "text-muted-foreground" },
};

export default function ResultsView({ results, onNewWorkflow, onStartWorkflow, workflowPrompt, activity, prompt, interpretation }) {
  const isFailure = results.status === "failed" || results.status === "needs_attention";
  const [showModal, setShowModal] = useState(false);
  const [showRunDetails, setShowRunDetails] = useState(false);
  const [copied, setCopied] = useState(false);
  const [deferred, setDeferred] = useState(results.deferred || []);
  const [showSchedule, setShowSchedule] = useState(false);

  useEffect(() => {
    setDeferred(results.deferred || []);
    if (!results.deferred || results.deferred.length === 0) return;
    const timer = window.setTimeout(() => {
      setDeferred((previous) => previous.map((item, index) => index === 0
        ? { ...item, arrived: "2 leads replied — Acme Corp confirmed a call for Thursday, and TechNova asked for pricing. Reply drafts are ready for your review." }
        : item));
    }, 9000);
    return () => window.clearTimeout(timer);
  }, [results.deferred]);

  const primaryResult = useMemo(() => selectPrimaryOutcome(results), [results]);
  const metrics = useMemo(() => meaningfulMetrics(results.metrics || []), [results.metrics]);
  const receipts = useMemo(
    () => supportingReceipts(results, activity || [], primaryResult),
    [activity, primaryResult, results]
  );
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
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full max-w-3xl mx-auto">
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: "spring", stiffness: 200, damping: 20 }}
        className="text-center mb-6"
      >
        <div className={`inline-flex p-3 rounded-2xl border mb-4 ${isFailure ? "bg-amber-400/10 border-amber-400/20" : "bg-emerald-400/10 border-emerald-400/20 glow-success"}`}>
          {isFailure
            ? <AlertTriangle className="w-8 h-8 text-amber-400" />
            : <CheckCircle2 className="w-8 h-8 text-emerald-400" />}
        </div>
        <h2 className="text-2xl font-bold mb-1">{results.title || "Workflow complete"}</h2>
        <p className="text-sm text-muted-foreground max-w-xl mx-auto">{results.summary}</p>
      </motion.div>

      {metrics.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6"
        >
          {metrics.map((metric, index) => (
            <div key={index} className="rounded-xl border border-white/[0.06] bg-card/40 p-4 text-center">
              <div className="text-2xl font-bold text-primary">{metric.value}</div>
              <div className="text-xs text-muted-foreground mt-1">{metric.label}</div>
            </div>
          ))}
        </motion.div>
      )}

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
                  Created in {primaryResult.provider}
                </span>
              )}
              <p className="mt-4 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60">Preview</p>
              <p className="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
                {primaryResult.detail || results.summary}
              </p>
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

      {receipts.length > 0 && (
        <motion.section
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.24 }}
          className="mb-5"
        >
          <h3 className="mb-3 text-sm font-medium">Also completed</h3>
          <div className="grid gap-2 sm:grid-cols-2">
            {receipts.map((receipt) => (
              <div key={receipt.key} className="flex items-start gap-2.5 rounded-xl border border-white/[0.06] bg-card/30 px-3.5 py-3">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                <div className="min-w-0">
                  <p className="text-[11px] font-medium text-muted-foreground">{receipt.tool}</p>
                  <p className="mt-0.5 text-sm leading-snug">{receipt.title}</p>
                </div>
              </div>
            ))}
          </div>
        </motion.section>
      )}

      {creatorsOutcome && <CreatorApprovalList items={creatorsOutcome.items} />}

      <motion.section
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="mb-5 overflow-hidden rounded-xl border border-white/[0.07] bg-card/25"
      >
        <button
          type="button"
          onClick={() => setShowRunDetails((visible) => !visible)}
          aria-expanded={showRunDetails}
          className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left hover:bg-white/[0.025]"
        >
          <span className="flex items-center gap-2 text-sm font-medium">
            <Activity className="h-4 w-4 text-primary" />
            {showRunDetails ? "Hide run details" : "View run details"}
          </span>
          <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${showRunDetails ? "rotate-180" : ""}`} />
        </button>

        {showRunDetails && (
          <div className="space-y-5 border-t border-white/[0.06] px-4 py-4">
            {activity?.length > 0 && (
              <div>
                <p className="mb-2.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/60">Workflow activity</p>
                <div className="space-y-2">
                  {activity.map((step, index) => {
                    const status = statusStyle[step.status] || statusStyle.pending;
                    return (
                      <div key={`${step.tool || "step"}-${index}`} className="flex gap-3 rounded-lg border border-white/5 bg-[#090f1e]/35 p-3">
                        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${status.dot}`} />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-xs font-medium">{step.tool || `Step ${index + 1}`}</p>
                            <span className={`text-[10px] ${status.text}`}>{status.label}</span>
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">{step.action}</p>
                          {step.liveOutput && <p className="mt-1 text-[11px] text-muted-foreground/70">{step.liveOutput}</p>}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {results.outcomes?.length > 0 && (
              <div>
                <p className="mb-2.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/60">Output receipts</p>
                <div className="space-y-2">
                  {results.outcomes.map((outcome, index) => (
                    <div key={index} className="space-y-1.5">
                      <ProofLine outcome={outcome} />
                      {outcome.items?.length > 0 && (
                        <div className="ml-4 grid gap-1.5 border-l border-white/[0.06] pl-4 sm:grid-cols-2">
                          {outcome.items.map((item, itemIndex) => (
                            <div key={itemIndex} className="rounded-lg bg-white/[0.025] px-3 py-2">
                              <p className="text-xs font-medium">{item.label}</p>
                              {item.detail && <p className="mt-0.5 text-[11px] text-muted-foreground">{item.detail}</p>}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {deferred.length > 0 && (
              <div>
                <p className="mb-2.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/60">Background receipts</p>
                <div className="space-y-2">
                  {deferred.map((item, index) => (
                    <div key={index} className="flex items-start gap-2.5 rounded-lg border border-white/5 bg-[#090f1e]/35 p-3">
                      {item.arrived
                        ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                        : <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-accent" />}
                      <div>
                        <p className="text-xs font-medium">{item.title}</p>
                        <p className="mt-1 text-[11px] text-muted-foreground">{item.arrived || item.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </motion.section>

      <motion.section
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.38 }}
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
        prompt={workflowPrompt}
        title={results.title}
      />
    </motion.div>
  );
}
