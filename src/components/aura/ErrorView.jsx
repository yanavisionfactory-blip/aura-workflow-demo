import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertOctagon, Pencil, SkipForward, Check, ChevronRight, ArrowRight, Clock3, Lightbulb, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { conjugateAction } from "@/lib/auraVerbs";

export default function ErrorView({
  error,
  step,
  runSteps,
  onRetry,
  onCheck,
  onEdit,
  onSkip,
  onAlternative,
  onSuggest,
  onLater,
  onCancel,
  busy = false,
  message = "",
}) {
  const [showDetails, setShowDetails] = useState(false);
  const [showSuggestion, setShowSuggestion] = useState(false);
  const [suggestion, setSuggestion] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);
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
          <p className="text-xs text-muted-foreground/70">{error.subtitle || "Nothing will continue until you choose what to do."}</p>
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

      {message && <p role="status" className="mb-4 text-sm text-amber-200">{message}</p>}
      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2 pt-4 border-t border-white/6">
        {onRetry && error.canRetry !== false && (
          <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
            <Button
              size="sm"
              onClick={onRetry}
              disabled={busy}
              className="bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700 text-white border-0 gap-1.5"
            >
              {busy ? "Checking…" : buttonLabel}
            </Button>
          </motion.div>
        )}
        {onCheck && error.canRetry === false && (
          <Button size="sm" onClick={onCheck} disabled={busy}>
            {busy ? "Checking…" : "Check latest status"}
          </Button>
        )}
        {onAlternative && (
          <Button variant="outline" size="sm" onClick={onAlternative} disabled={busy} className="gap-1.5 border-white/10">
            <Lightbulb className="w-3.5 h-3.5" />
            Ask AURA for another solution
          </Button>
        )}
        {onSuggest && (
          <Button variant="ghost" size="sm" onClick={() => setShowSuggestion((value) => !value)} disabled={busy}>
            Suggest my own
          </Button>
        )}
        {onEdit && <Button disabled={busy} variant="outline" size="sm" onClick={onEdit} className="gap-1.5 border-white/10">
          <Pencil className="w-3.5 h-3.5" />
          Edit
        </Button>}
        {onSkip && <Button disabled={busy} variant="ghost" size="sm" onClick={onSkip} className="text-muted-foreground gap-1.5">
          <SkipForward className="w-3.5 h-3.5" />
          Skip optional step
        </Button>}
        {onLater && (
          <Button disabled={busy} variant="ghost" size="sm" onClick={onLater} className="text-muted-foreground gap-1.5">
            <Clock3 className="w-3.5 h-3.5" />
            Keep for later
          </Button>
        )}
      </div>

      <AnimatePresence initial={false}>
        {showSuggestion && onSuggest && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="mt-3 rounded-xl border border-white/8 bg-card/50 p-3">
              <label htmlFor="error-recovery-suggestion" className="text-xs font-medium">
                How should AURA approach it instead?
              </label>
              <textarea
                id="error-recovery-suggestion"
                value={suggestion}
                onChange={(event) => setSuggestion(event.target.value)}
                rows={2}
                autoFocus
                placeholder="Describe a different account, source, or safe approach…"
                className="mt-2 w-full resize-none rounded-lg border border-white/10 bg-background/50 px-3 py-2 text-sm outline-none placeholder:text-muted-foreground/50 focus:border-primary/50"
              />
              <div className="mt-2 flex justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={() => setShowSuggestion(false)} disabled={busy}>Cancel</Button>
                <Button size="sm" onClick={() => onSuggest(suggestion.trim())} disabled={busy || !suggestion.trim()}>
                  Build revised plan
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {onCancel && (
        <div className="mt-3 border-t border-white/6 pt-3">
          {confirmCancel ? (
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>Cancel this saved run? Completed provider work will not be undone.</span>
              <Button size="sm" variant="destructive" onClick={onCancel} disabled={busy}>Cancel run</Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmCancel(false)} disabled={busy}>Keep it</Button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmCancel(true)}
              disabled={busy}
              className="flex items-center gap-1.5 text-xs text-muted-foreground/70 transition-colors hover:text-red-300 disabled:opacity-40"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Cancel saved run
            </button>
          )}
        </div>
      )}
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
