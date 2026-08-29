import { motion, AnimatePresence } from "framer-motion";
import { X, CheckCircle2, Clock, FileDown } from "lucide-react";
import { buildSummaryText } from "@/lib/auraSummary";
import { conjugateAction } from "@/lib/auraVerbs";
import { INTERFACE_TOOLS } from "@/lib/demoData";

// Compute a compact wall-clock label for a step. Steps may carry an explicit
// `time` (e.g. "10:03") from the mock; otherwise derive one from the order.
function stepTime(s, i) {
  if (s.time) return s.time;
  const total = 2 + i; // start ~10:02, +1 min each
  const h = 10 + Math.floor(total / 60);
  const m = total % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}

// A start-to-finish timeline of everything AURA did, with a downloadable recap.
export default function FullActivityModal({
  open,
  onClose,
  activity,
  title,
  summary,
  prompt,
  interpretation,
  outcomes,
  metrics,
  nextSteps,
}) {
  const steps = activity || [];

  const handleDownload = () => {
    const text = buildSummaryText({
      title,
      summary,
      metrics,
      outcomes,
      activity: steps,
      prompt,
      interpretation,
      nextSteps,
    });
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aura-summary-${(title || "workflow")
      .replace(/\s+/g, "-")
      .toLowerCase()}.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <AnimatePresence>
      {open && (
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
            <div className="w-full max-w-xl max-h-[82vh] flex flex-col bg-card border border-white/10 rounded-2xl shadow-2xl pointer-events-auto overflow-hidden">
              <div className="flex items-center gap-2 px-5 py-4 border-b border-white/6">
                <Clock className="w-4 h-4 text-primary" />
                <h3 className="text-sm font-semibold">Full activity</h3>
                <span className="text-[10px] text-muted-foreground/50">
                  {steps.length} steps · start to finish
                </span>
                <button
                  onClick={onClose}
                  className="ml-auto p-1.5 rounded-lg hover:bg-white/8 text-muted-foreground hover:text-foreground transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-4">
                {summary && (
                  <div className="mb-4 p-3 rounded-xl bg-emerald-400/5 border border-emerald-400/15 flex items-start gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm font-medium">{title}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">{summary}</p>
                    </div>
                  </div>
                )}

                <ol className="space-y-3">
                  {steps.map((s, i) => {
                    const isModify = s.riskLevel === "modify";
                    return (
                      <motion.li
                        key={i}
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.05 }}
                        className="flex gap-3"
                      >
                        <div className="flex flex-col items-center flex-shrink-0">
                          <div className="w-6 h-6 rounded-full bg-emerald-400/15 border border-emerald-400/30 flex items-center justify-center">
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                          </div>
                          {i < steps.length - 1 && (
                            <div className="w-px flex-1 bg-white/8 mt-1" />
                          )}
                        </div>
                        <div className="flex-1 min-w-0 pb-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[10px] tabular-nums text-muted-foreground/45">
                              {stepTime(s, i)}
                            </span>
                            <span className="text-[11px] font-medium text-muted-foreground/60">
                              {s.tool}
                            </span>
                            {INTERFACE_TOOLS[s.tool] && (
                              <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                                via AURA Interface
                              </span>
                            )}
                            {isModify && (
                              <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-400/10 text-amber-300/80 border border-amber-400/20">
                                modify
                              </span>
                            )}
                            {s.duration && (
                              <span className="text-[10px] text-muted-foreground/40">
                                {s.duration}
                              </span>
                            )}
                          </div>
                          <p className="text-sm mt-0.5">
                            {conjugateAction(String(s.action).replace(/…$/, ""), "past")}
                          </p>
                          {s.note && (
                            <p className="text-[11px] text-muted-foreground/70 mt-1 flex items-center gap-1">
                              <CheckCircle2 className="w-3 h-3 text-emerald-400/70" />
                              {s.note}
                            </p>
                          )}
                        </div>
                      </motion.li>
                    );
                  })}
                </ol>
              </div>

              <div className="px-4 py-3 border-t border-white/6 flex items-center justify-between gap-2">
                <span className="text-[11px] text-muted-foreground/50">
                  A complete record of everything AURA did.
                </span>
                <button
                  onClick={handleDownload}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-white/10 hover:bg-white/5 transition-colors"
                >
                  <FileDown className="w-3.5 h-3.5" /> Download summary
                </button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}