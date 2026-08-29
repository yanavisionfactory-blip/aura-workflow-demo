import { motion } from "framer-motion";
import { Check, Loader2, Clock, AlertTriangle, ArrowRight, Plug, PlugZap } from "lucide-react";
import { connectionFor } from "@/lib/demoData";
import { conjugateAction } from "@/lib/auraVerbs";

const statusConfig = {
  pending: {
    icon: Clock,
    color: "text-muted-foreground/40",
    bg: "bg-muted/30 border-white/5",
    label: "Waiting",
  },
  running: {
    icon: Loader2,
    color: "text-accent",
    bg: "bg-accent/10 border-accent/20 glow-accent",
    label: "Executing",
    spin: true,
  },
  completed: {
    icon: Check,
    color: "text-emerald-400",
    bg: "bg-emerald-400/10 border-emerald-400/20 glow-success",
    label: "Done",
  },
  failed: {
    icon: AlertTriangle,
    color: "text-amber-400",
    bg: "bg-amber-400/10 border-amber-400/20",
    label: "Needs attention",
  },
  decision: {
    icon: ArrowRight,
    color: "text-amber-400",
    bg: "bg-amber-400/10 border-amber-400/20",
    label: "Decision made",
  },
};

export default function ExecutionStep({ step, index, isLast }) {
  const config = statusConfig[step.status] || statusConfig.pending;
  const Icon = config.icon;
  const displayAction =
    step.status === "completed"
      ? conjugateAction(step.action, "past")
      : step.status === "running"
      ? conjugateAction(step.action, "ing")
      : step.action;
  const connected = connectionFor(step.tool);
  const isModify = step.riskLevel === "modify";

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }} className="relative">
      {!isLast && (
        <div
          className={`absolute left-5 top-12 bottom-0 w-px ${
            step.status === "completed" ? "bg-emerald-400/20" : step.status === "failed" ? "bg-amber-400/20" : "bg-white/5"
          }`}
        />
      )}

      <div className="flex gap-4">
        <div
          className={`relative z-10 flex-shrink-0 w-10 h-10 rounded-xl border flex items-center justify-center transition-all duration-500 ${config.bg}`}
        >
          <Icon className={`w-4 h-4 ${config.color} ${config.spin ? "animate-spin" : ""}`} />
          {step.status === "running" && (
            <div className="absolute inset-0 rounded-xl border-2 border-accent/30 animate-pulse-ring" />
          )}
        </div>

        <div className="flex-1 pb-5">
          <div
            className={`rounded-xl border transition-all duration-500 overflow-hidden ${
              step.status === "completed"
                ? "border-emerald-400/10 bg-emerald-400/[0.02]"
                : step.status === "running"
                ? "border-accent/20 bg-accent/[0.02]"
                : step.status === "failed"
                ? "border-amber-400/20 bg-amber-400/[0.02]"
                : "border-white/5 bg-card/30"
            }`}
          >
            <div className="p-3">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[11px] font-medium text-muted-foreground/60">{step.tool}</span>
                  {connected ? (
                    <span className="flex items-center gap-0.5 text-[10px] text-emerald-400/70">
                      <Plug className="w-2.5 h-2.5" />
                    </span>
                  ) : (
                    <span className="flex items-center gap-0.5 text-[10px] text-amber-400/80">
                      <PlugZap className="w-2.5 h-2.5" />
                    </span>
                  )}
                  {isModify && (
                    <span className="text-[10px] text-amber-400/70 flex items-center gap-0.5">
                      <AlertTriangle className="w-2.5 h-2.5" />
                    </span>
                  )}
                  <span className={`text-[10px] font-medium ${config.color}`}>{config.label}</span>
                </div>
                {step.duration && (
                  <span className="text-[10px] text-muted-foreground/40">{step.duration}</span>
                )}
              </div>
              <p className="text-sm">{displayAction}</p>
              {step.liveOutput && (
                <p className="text-xs text-accent/80 mt-1.5 font-mono leading-relaxed break-words">{step.liveOutput}</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}