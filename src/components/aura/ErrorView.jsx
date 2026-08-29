import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertOctagon, Pencil, SkipForward, Check, ChevronRight, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { conjugateAction } from "@/lib/auraVerbs";

export default function ErrorView({ error, step, runSteps, onRetry, onEdit, onSkip }) {
  const [showDetails, setShowDetails] = useState(false);
  if (!error) return null;

  const steps = runSteps || [];
  const completed = steps.filter((s) => s.status === "completed");
  const failedIdx = steps.findIndex((s) => s.status === "failed");
  const stepNumber = (error.index != null ? error.index : failedIdx >= 0 ? failedIdx : 0) + 1;
  const buttonLabel = error.buttonLabel || "Apply fix & retry";

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.4 }}
      className="w-full max-w-2xl mx-auto"
    >
      {/* Header */}
      <div className="flex items-center gap-3 mb-5">
        <div className="p-2 rounded-xl bg-amber-400/10 border border-amber-400/20">
          <AlertOctagon className="w-5 h-5 text-amber-400" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">AURA paused — something needs attention</h2>
          <p className="text-xs text-muted-foreground/70">Nothing will continue until you choose what to do.</p>
        </div>
      </div>

      {/* Failed step */}
      {step && (
        <div className="mb-3 p-3 rounded-xl border border-amber-400/15 bg-amber-400/[0.03]">
          <span className="text-[10px] uppercase tracking-wider text-amber-400/70 font-medium">
            Step {stepNumber} · {step.tool}
          </span>
          <p className="text-sm mt-0.5">{step.action}</p>
        </div>
      )}

      {/* What / Why / Fix */}
      <div className="space-y-2.5 mb-4">
        <DetailRow label="What happened" text={error.what} />
        <DetailRow label="Why" text={error.why} />
        <div className="p-3.5 rounded-xl border border-emerald-400/15 bg-emerald-400/[0.03]">
          <span className="text-[10px] uppercase tracking-wider text-emerald-400/70 font-medium">Suggested fix</span>
          <p className="text-sm mt-0.5">{error.fixShort || error.fix}</p>
          {error.fixFrom && error.fixTo && (
            <div className="mt-2 flex items-center gap-2 text-xs">
              <span className="line-through text-muted-foreground/50">{error.fixFrom}</span>
              <ArrowRight className="w-3 h-3 text-emerald-400" />
              <span className="font-medium text-emerald-300">{error.fixTo}</span>
            </div>
          )}
        </div>
      </div>

      {/* Compact progress line */}
      {completed.length > 0 && (
        <div className="mb-4">
          <button
            onClick={() => setShowDetails((s) => !s)}
            className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <Check className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
            <span className="flex-1 text-left">{completed.length} of {steps.length} steps already completed</span>
            <span className="flex items-center gap-0.5 text-primary">
              {showDetails ? "Hide" : "View details"}
              <ChevronRight className={`w-3 h-3 transition-transform ${showDetails ? "rotate-90" : ""}`} />
            </span>
          </button>
          <AnimatePresence initial={false}>
            {showDetails && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className="pl-6 pt-2.5 space-y-1">
                  {steps.map((s, i) => {
                    if (s.status !== "completed" && s.status !== "failed") return null;
                    const failed = s.status === "failed";
                    const label = String(s.action || "").replace(/…$/, "");
                    return (
                      <div key={i} className="flex items-center gap-2 text-xs">
                        {failed ? (
                          <AlertOctagon className="w-3 h-3 text-amber-400 flex-shrink-0" />
                        ) : (
                          <Check className="w-3 h-3 text-emerald-400 flex-shrink-0" />
                        )}
                        <span className="text-muted-foreground/50">{s.tool}</span>
                        <span className={failed ? "text-amber-200/90" : "text-muted-foreground"}>
                          {failed ? label : conjugateAction(label, "past")}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2 pt-4 border-t border-white/6">
        <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
          <Button
            size="sm"
            onClick={onRetry}
            className="bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700 text-white border-0 gap-1.5"
          >
            {buttonLabel}
          </Button>
        </motion.div>
        <Button variant="outline" size="sm" onClick={onEdit} className="gap-1.5 border-white/10">
          <Pencil className="w-3.5 h-3.5" />
          Edit
        </Button>
        <Button variant="ghost" size="sm" onClick={onSkip} className="text-muted-foreground gap-1.5">
          <SkipForward className="w-3.5 h-3.5" />
          Skip
        </Button>
      </div>
    </motion.div>
  );
}

function DetailRow({ label, text }) {
  return (
    <div className="p-3 rounded-xl border border-white/8 bg-card/50">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 font-medium">{label}</span>
      <p className="text-sm mt-0.5">{text}</p>
    </div>
  );
}