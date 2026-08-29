import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  Eye,
  AlertTriangle,
  ShieldCheck,
  ArrowRight,
  Plug,
  PlugZap,
} from "lucide-react";
import { connectionFor } from "@/lib/demoData";

// Shows exactly what AURA will do for a single plan step — before the user runs anything.
export default function StepPreviewModal({ step, index, open, onClose }) {
  const connected = connectionFor(step.tool);
  const isModify = step.riskLevel === "modify";

  return (
    <AnimatePresence>
      {open && step && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 16 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 16 }}
            transition={{ type: "spring", stiffness: 260, damping: 24 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
          >
            <div className="w-full max-w-md max-h-[82vh] flex flex-col bg-card border border-white/10 rounded-2xl shadow-2xl pointer-events-auto overflow-hidden">
              {/* Header */}
              <div className="flex items-center gap-2 px-5 py-4 border-b border-white/6">
                <div className="p-1.5 rounded-lg bg-primary/10 flex-shrink-0">
                  <Eye className="w-4 h-4 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <span className="text-[10px] uppercase tracking-wider text-primary/60 font-medium">
                    Step {index + 1} preview
                  </span>
                  <h3 className="text-sm font-semibold leading-snug">
                    What AURA will do
                  </h3>
                </div>
                <button
                  onClick={onClose}
                  className="p-1.5 rounded-lg hover:bg-white/8 text-muted-foreground hover:text-foreground transition-colors flex-shrink-0"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Body */}
              <div className="flex-1 overflow-y-auto p-4 space-y-3.5">
                {/* Tool + status row */}
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground/60">
                    {step.tool}
                  </span>
                  {connected ? (
                    <span className="flex items-center gap-1 text-[10px] text-emerald-400/80">
                      <Plug className="w-2.5 h-2.5" /> Connected
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-[10px] text-amber-400/90">
                      <PlugZap className="w-2.5 h-2.5" /> Not connected yet
                    </span>
                  )}
                  {isModify ? (
                    <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-400/10 border border-amber-400/20 text-amber-400">
                      <AlertTriangle className="w-2.5 h-2.5" /> Modifies data
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-400/10 border border-emerald-400/20 text-emerald-400/80">
                      <ShieldCheck className="w-2.5 h-2.5" /> Read-only
                    </span>
                  )}
                </div>

                {/* The action */}
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
                    Action
                  </span>
                  <p className="text-sm mt-0.5">{step.action}</p>
                </div>

                {/* How it works (technical) */}
                {step.detail && (
                  <div>
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
                      How it works
                    </span>
                    <p className="text-[11px] text-muted-foreground/70 mt-0.5 font-mono leading-relaxed bg-secondary/40 border border-white/5 rounded-lg px-2.5 py-2">
                      {step.detail}
                    </p>
                  </div>
                )}

                {/* Why */}
                {step.reason && (
                  <div>
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
                      Why this step
                    </span>
                    <p className="text-xs text-muted-foreground mt-0.5">{step.reason}</p>
                  </div>
                )}

                {/* Expected result */}
                {step.output && (
                  <div className="p-3 rounded-xl border border-primary/15 bg-primary/[0.04]">
                    <span className="text-[10px] uppercase tracking-wider text-primary/60 font-medium">
                      Expected result
                    </span>
                    <div className="flex items-start gap-1.5 mt-1">
                      <ArrowRight className="w-3.5 h-3.5 text-primary/70 mt-0.5 flex-shrink-0" />
                      <p className="text-sm text-foreground/90">{step.output}</p>
                    </div>
                  </div>
                )}

                {/* Risk note */}
                {isModify && step.riskNote && (
                  <div className="flex items-start gap-1.5 p-2.5 rounded-lg bg-amber-400/5 border border-amber-400/20">
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-400 mt-0.5 flex-shrink-0" />
                    <p className="text-[11px] text-amber-300/90 leading-snug">
                      {step.riskNote}
                    </p>
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="px-4 py-3 border-t border-white/6">
                <p className="text-[11px] text-muted-foreground/50 text-center">
                  Nothing runs until you approve the full plan.
                </p>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}