import { useState, useEffect, useMemo } from "react";
import { motion } from "framer-motion";
import {
  CheckCircle2,
  ArrowRight,
  BarChart3,
  RefreshCw,
  Zap,
  Activity,
  Share2,
  Check,
  FileDown,
  Eye,
  Clock,
  Loader2,
  CalendarClock,
  ChevronDown,
  Plus,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import ProofLine from "./ProofLine";
import AccessRequestModal from "./AccessRequestModal";
import BreakdownTable from "./BreakdownTable";
import ScheduleModal from "./ScheduleModal";
import OutcomeDetailModal from "./OutcomeDetailModal";
import FullActivityModal from "./FullActivityModal";
import CreatorApprovalList from "./CreatorApprovalList";
import { buildSummaryText } from "@/lib/auraSummary";
import { INTERFACE_TOOLS } from "@/lib/demoData";

export default function ResultsView({ results, onNewWorkflow, onStartWorkflow, workflowPrompt, activity, prompt, interpretation }) {
  const [showModal, setShowModal] = useState(false);
  const [detailOutcome, setDetailOutcome] = useState(null);
  const [showActivity, setShowActivity] = useState(false);
  const [showOutput, setShowOutput] = useState(false);
  const [copied, setCopied] = useState(false);
  const [deferred, setDeferred] = useState(results.deferred || []);
  const [showSchedule, setShowSchedule] = useState(false);

  useEffect(() => {
    setDeferred(results.deferred || []);
    if (!results.deferred || results.deferred.length === 0) return;
    const t = setTimeout(() => {
      setDeferred((prev) =>
        prev.map((d, i) =>
          i === 0
            ? { ...d, arrived: "2 leads replied — Acme Corp confirmed a call for Thursday, and TechNova asked for pricing. Reply drafts are ready for your review." }
            : d
        )
      );
    }, 9000);
    return () => clearTimeout(t);
  }, [results.deferred]);

  const summaryArgs = {
    title: results.title,
    summary: results.summary,
    metrics: results.metrics,
    outcomes: results.outcomes,
    activity,
    prompt,
    interpretation,
    nextSteps: results.nextSteps,
  };

  const handleShare = async () => {
    const text = buildSummaryText(summaryArgs);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      /* clipboard unavailable */
    }
  };

  const handleDownload = () => {
    const text = buildSummaryText(summaryArgs);
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aura-summary-${(results.title || "workflow").replace(/\s+/g, "-").toLowerCase()}.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  // The concrete, tabular output shown in the "Results" section when there's
  // no dedicated breakdown table.
  const outputOutcome = (results.outcomes || []).find((o) => o.items && o.items.length > 0 && o.type !== "creators");
  // Creators pending the manager's approval (creator-outreach runs only).
  const creatorsOutcome = (results.outcomes || []).find((o) => o.type === "creators" && o.items && o.items.length > 0);

  // Distinct external tools that actually ran (from the live activity), with
  // their connection source. Interface tools are tagged "via AURA Interface"
  // so the difficult-connection arc is visible in the proof block.
  const toolsUsed = useMemo(() => {
    const seen = new Set();
    const out = [];
    (activity || []).forEach((s) => {
      const name = s.tool;
      if (!name || name === "AURA Intelligence" || seen.has(name)) return;
      seen.add(name);
      out.push({ name, viaInterface: !!INTERFACE_TOOLS[name] });
    });
    return out;
  }, [activity]);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full max-w-3xl mx-auto">
      {/* Completion header */}
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: "spring", stiffness: 200, damping: 20 }}
        className="text-center mb-6"
      >
        <div className="inline-flex p-3 rounded-2xl bg-emerald-400/10 border border-emerald-400/20 mb-4 glow-success">
          <CheckCircle2 className="w-8 h-8 text-emerald-400" />
        </div>
        <h2 className="text-2xl font-bold mb-1">{results.title || "Workflow complete"}</h2>
        <p className="text-sm text-muted-foreground max-w-xl mx-auto">{results.summary}</p>
      </motion.div>

      {/* Key metrics */}
      {results.metrics && results.metrics.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="grid grid-cols-3 gap-3 mb-6"
        >
          {results.metrics.map((m, i) => (
            <div key={i} className="rounded-xl border border-white/6 bg-card/40 p-4 text-center">
              <div className="text-2xl font-bold">{m.value}</div>
              <div className="text-xs text-muted-foreground mt-1">{m.label}</div>
            </div>
          ))}
        </motion.div>
      )}

      {/* What happened */}
      {results.outcomes && results.outcomes.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="mb-6"
        >
          <h3 className="text-sm font-medium mb-3">What happened</h3>
          <div className="space-y-2">
            {results.outcomes.map((outcome, i) => (
              <ProofLine key={i} outcome={outcome} onDetails={() => setDetailOutcome(i)} />
            ))}
          </div>
        </motion.div>
      )}

      {/* Creators pending approval — approve here, AURA sends the email later */}
      {creatorsOutcome && <CreatorApprovalList items={creatorsOutcome.items} />}

      {/* Tools used — per-tool proof, with the View activity entry point */}
      {toolsUsed.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.28 }}
          className="mb-6 p-4 rounded-xl border border-white/6 bg-card/40"
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Wrench className="w-3.5 h-3.5 text-muted-foreground/70" />
              <h3 className="text-sm font-medium">Tools used</h3>
            </div>
            <button
              onClick={() => setShowActivity(true)}
              className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-full border border-primary/20 text-primary hover:bg-primary/10 transition-colors"
            >
              <Activity className="w-3 h-3" /> View activity
            </button>
          </div>
          <div className="flex flex-wrap gap-2 mt-3">
            {toolsUsed.map((t) => (
              <div
                key={t.name}
                className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-secondary/40 border border-white/8"
              >
                <Check className="w-3 h-3 text-emerald-400" />
                <span className="font-medium">{t.name}</span>
                {t.viaInterface && (
                  <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                    via AURA Interface
                  </span>
                )}
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {/* Results — the actual useful output (table / report / document) */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35 }}
        className="mb-6"
      >
        <button
          onClick={() => setShowOutput((s) => !s)}
          className="flex items-center gap-2 text-sm font-medium hover:text-primary transition-colors"
        >
          <BarChart3 className="w-4 h-4 text-primary" />
          <span>Results</span>
          <span className="text-[11px] text-muted-foreground">— the actual output</span>
          <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${showOutput ? "rotate-180" : ""}`} />
        </button>
        {showOutput &&
          (results.breakdown ? (
            <div className="mt-3">
              <BreakdownTable breakdown={results.breakdown} />
            </div>
          ) : outputOutcome ? (
            <div className="mt-3 rounded-xl border border-white/6 bg-card/40 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/5 bg-card/30">
                      <th className="text-left font-medium text-muted-foreground/60 px-4 py-2 whitespace-nowrap">Item</th>
                      <th className="text-left font-medium text-muted-foreground/60 px-4 py-2 whitespace-nowrap">What happened</th>
                    </tr>
                  </thead>
                  <tbody>
                    {outputOutcome.items.map((it, i) => (
                      <tr key={i} className="border-b border-white/[0.03] last:border-0 hover:bg-white/[0.02]">
                        <td className="px-4 py-2 whitespace-nowrap font-medium">{it.label}</td>
                        <td className="px-4 py-2 text-muted-foreground">{it.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">No structured output for this run.</p>
          ))}
      </motion.div>

      {/* Still tracking — deferred results */}
      {deferred.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.45 }} className="mb-5">
          <h3 className="text-sm font-medium mb-3 flex items-center gap-2">
            <Clock className="w-4 h-4 text-accent" />
            Still tracking
          </h3>
          <div className="space-y-2">
            {deferred.map((d, i) => (
              <div
                key={i}
                className={`p-3 rounded-xl border flex items-start gap-3 ${
                  d.arrived ? "border-emerald-400/20 bg-emerald-400/[0.03]" : "border-accent/20 bg-card/30"
                }`}
              >
                {d.arrived ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
                ) : (
                  <Loader2 className="w-4 h-4 text-accent flex-shrink-0 mt-0.5 animate-spin" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-sm font-medium">{d.title}</p>
                    {!d.arrived && d.eta && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20">{d.eta}</span>
                    )}
                    {d.arrived && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-400/10 text-emerald-400 border border-emerald-400/20">Arrived</span>
                    )}
                  </div>
                  {d.arrived ? (
                    <p className="text-xs text-muted-foreground mt-1">{d.arrived}</p>
                  ) : (
                    <p className="text-xs text-muted-foreground mt-1">{d.detail}</p>
                  )}
                  {!d.arrived && (
                    <p className="text-[11px] text-muted-foreground/50 mt-1">Aura will keep watching and surface the outcome here when it's ready.</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {/* Suggested next */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }} className="mb-5">
        <h3 className="text-sm font-medium mb-3 flex items-center gap-2">
          <ArrowRight className="w-4 h-4 text-primary" />
          Suggested next
        </h3>
        <div className="flex flex-wrap gap-2">
          {results.nextSteps.map((step, i) => (
            <button
              key={i}
              onClick={() => onStartWorkflow(step)}
              className="text-xs px-3 py-1.5 rounded-full border border-primary/20 text-primary hover:bg-primary/10 transition-colors"
            >
              {step}
            </button>
          ))}
        </div>
      </motion.div>

      {/* Run this again? */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.55 }}
        className="mt-2 mb-4 p-4 rounded-2xl border border-primary/15 bg-primary/[0.04]"
      >
        <div className="flex items-center gap-2 mb-1">
          <p className="text-sm font-medium">What would you like to do next?</p>
        </div>
        <p className="text-[11px] text-muted-foreground/70 mb-3">Run it again, automate it for later, or start something new.</p>
        <div className="flex gap-2">
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => onStartWorkflow(prompt)}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 text-sm font-medium transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Run again
          </motion.button>
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => setShowSchedule(true)}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl bg-gradient-to-r from-primary to-accent text-white text-sm font-semibold shadow-lg shadow-primary/20"
          >
            <CalendarClock className="w-4 h-4" />
            Schedule
          </motion.button>
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={onNewWorkflow}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" />
            New workflow
          </motion.button>
        </div>
      </motion.div>

      {/* Action footer — proof + connect */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6 }}
        className="flex items-center justify-between gap-3 flex-wrap pt-4 border-t border-white/6"
      >
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowActivity(true)} className="gap-1.5 border-white/10 text-xs">
            <Activity className="w-3.5 h-3.5" /> Activity
          </Button>
          <Button variant="outline" size="sm" onClick={handleShare} className="gap-1.5 border-white/10 text-xs">
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Share2 className="w-3.5 h-3.5" />}
            {copied ? "Copied" : "Share"}
          </Button>
          <Button variant="outline" size="sm" onClick={handleDownload} className="gap-1.5 border-white/10 text-xs">
            <FileDown className="w-3.5 h-3.5" /> Download
          </Button>
        </div>
        <motion.button
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          onClick={() => setShowModal(true)}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-gradient-to-r from-primary to-accent text-white text-xs font-semibold shadow-lg shadow-primary/20"
        >
          <Zap className="w-3.5 h-3.5" /> Connect & run for real
        </motion.button>
      </motion.div>

      <OutcomeDetailModal
        outcome={detailOutcome != null ? results.outcomes[detailOutcome] : null}
        open={detailOutcome != null}
        onClose={() => setDetailOutcome(null)}
      />
      <FullActivityModal
        open={showActivity}
        onClose={() => setShowActivity(false)}
        activity={activity}
        title={results.title}
        summary={results.summary}
        prompt={prompt}
        interpretation={interpretation}
        outcomes={results.outcomes}
        metrics={results.metrics}
        nextSteps={results.nextSteps}
      />

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