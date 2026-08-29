import { motion } from "framer-motion";
import { Activity, Zap, Clock } from "lucide-react";
import ExecutionStep from "./ExecutionStep";

const STEP_DURATION = 2.6; // seconds per step (for ETA)

export default function ExecutionView({ steps, currentStepIndex, isReal }) {
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

      {/* Steps */}
      <div>
        {steps.map((step, i) => (
          <ExecutionStep key={i} step={step} index={i} isLast={i === steps.length - 1} isCurrent={i === currentStepIndex} />
        ))}
      </div>

      {!failed && (
        <div className="flex items-center justify-center gap-1.5 mt-4 text-[11px] text-muted-foreground/50">
          <Clock className="w-3 h-3" />
          Safe to leave this page — we'll notify you when it's done or if something needs you
        </div>
      )}
    </motion.div>
  );
}