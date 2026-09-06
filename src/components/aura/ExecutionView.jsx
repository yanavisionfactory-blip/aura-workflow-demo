import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Activity, Zap, Clock, ChevronDown } from "lucide-react";
import ExecutionStep from "./ExecutionStep";

const STEP_DURATION = 2.6; // seconds per step (for ETA)

export default function ExecutionView({ steps, currentStepIndex, isReal, workflowSummary }) {
  const [showActivity, setShowActivity] = useState(false);
  const completedCount = steps.filter((s) => s.status === "completed").length;
  const failed = steps.some((s) => s.status === "failed");
  const progress = (completedCount / steps.length) * 100;
  const remaining = Math.max(0, steps.length - completedCount);
  const etaSecs = remaining > 0 && !failed ? remaining * STEP_DURATION : 0;
  const eta = failed
    ? null
    : isReal
    ? remaining > 0
      ? "Working… this can take up to a minute"
      : null
    : !etaSecs
    ? null
    : etaSecs >= 60
    ? `About ${Math.max(1, Math.round(etaSecs / 60))} min remaining`
    : `~${Math.round(etaSecs)}s remaining`;
  const currentStep = steps[currentStepIndex] || steps.find((step) => step.status === "pending") || steps.at(-1);
  const currentLabel = currentStep?.status === "completed"
    ? "Finishing up"
    : currentStep?.action || "Preparing the next step";

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full max-w-3xl mx-auto">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between mb-5"
      >
        <div className="flex items-center gap-3">
          <div className="relative p-2 rounded-xl bg-accent/10 border border-accent/20">
            <Activity className="w-5 h-5 text-accent" />
            {failed ? null : <div className="absolute inset-0 rounded-xl bg-accent/20 animate-pulse" />}
          </div>
          <div>
            <h2 className="text-lg font-semibold">{failed ? "Workflow paused" : "Running your workflow"}</h2>
            <p className="text-xs text-muted-foreground">
              Step {Math.min(currentStepIndex + 1, steps.length)} of {steps.length}
              {eta ? ` · ${eta}` : ""}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Zap className="w-3.5 h-3.5 text-accent" />
          <span className="text-sm font-mono text-accent">
            {completedCount}/{steps.length}
          </span>
        </div>
      </motion.div>

      {/* Progress bar */}
      <div className="mb-6 h-1 rounded-full bg-white/5 overflow-hidden">
        <motion.div
          className="h-full rounded-full bg-gradient-to-r from-accent to-primary"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
      </div>

      <div className="rounded-2xl border border-accent/15 bg-accent/[0.03] p-5">
        <p className="text-[10px] uppercase tracking-[0.16em] text-accent/70">What AURA is doing</p>
        <h3 className="mt-1.5 text-base font-semibold">{workflowSummary || "Completing your workflow"}</h3>
        <p className="mt-3 text-sm text-muted-foreground">
          Now: <span className="text-foreground">{currentLabel}</span>
        </p>
      </div>

      <button
        type="button"
        onClick={() => setShowActivity((value) => !value)}
        className="mt-4 flex w-full items-center justify-between rounded-xl border border-sky-400/15 bg-sky-400/[0.04] px-4 py-3 text-sm text-sky-300 hover:bg-sky-400/[0.08]"
      >
        <span>{showActivity ? "Hide activity" : `Show activity · ${completedCount} of ${steps.length} complete`}</span>
        <ChevronDown className={`h-4 w-4 transition-transform ${showActivity ? "rotate-180" : ""}`} />
      </button>

      <AnimatePresence initial={false}>
        {showActivity && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="mt-4 overflow-hidden">
            {steps.map((step, i) => (
              <ExecutionStep key={i} step={step} index={i} isLast={i === steps.length - 1} />
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {!failed && (
        <div className="flex items-center justify-center gap-1.5 mt-4 text-[11px] text-muted-foreground/50">
          <Clock className="w-3 h-3" />
          Safe to leave this page — we'll notify you when it's done or if something needs you
        </div>
      )}
    </motion.div>
  );
}
