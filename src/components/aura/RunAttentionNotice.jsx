import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, ArrowRight, Clock3, Lightbulb, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function RunAttentionNotice({
  run,
  recovery,
  busy = false,
  message = "",
  onReview,
  onAlternative,
  onSuggest,
  onLater,
  onCancel,
}) {
  const [showSuggestion, setShowSuggestion] = useState(false);
  const [suggestion, setSuggestion] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);
  if (!run || !recovery) return null;

  const workflowName = run.plan?.name || "Saved workflow";
  const submitSuggestion = () => {
    const value = suggestion.trim();
    if (!value || busy) return;
    onSuggest(value);
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-5 rounded-2xl border border-amber-400/20 bg-amber-400/[0.04] p-4 shadow-lg shadow-black/10"
      aria-labelledby="saved-run-attention-title"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-xl border border-amber-400/20 bg-amber-400/10 p-2">
          <AlertTriangle className="h-4 w-4 text-amber-300" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p id="saved-run-attention-title" className="text-sm font-semibold">
                One saved workflow needs your attention
              </p>
              <p className="mt-0.5 truncate text-xs text-muted-foreground">{workflowName}</p>
            </div>
            <button
              type="button"
              onClick={onLater}
              disabled={busy}
              aria-label="Keep this workflow for later"
              className="rounded-lg p-1 text-muted-foreground/60 transition-colors hover:bg-white/5 hover:text-foreground disabled:opacity-40"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <p className="mt-3 text-sm text-foreground/90">{recovery.what}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{recovery.fix}</p>

          {message && <p role="status" className="mt-3 text-xs text-amber-200">{message}</p>}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={onReview} disabled={busy} className="gap-1.5">
              Review & choose
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
            <Button size="sm" variant="outline" onClick={onAlternative} disabled={busy} className="gap-1.5 border-white/10">
              <Lightbulb className="h-3.5 w-3.5" />
              Ask AURA for another solution
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setShowSuggestion((value) => !value)}
              disabled={busy}
            >
              Suggest my own
            </Button>
            <Button size="sm" variant="ghost" onClick={onLater} disabled={busy} className="gap-1.5 text-muted-foreground">
              <Clock3 className="h-3.5 w-3.5" />
              Keep for later
            </Button>
          </div>

          <AnimatePresence initial={false}>
            {showSuggestion && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className="mt-3 rounded-xl border border-white/8 bg-background/40 p-3">
                  <label htmlFor="recovery-suggestion" className="text-xs font-medium">
                    How should AURA approach it instead?
                  </label>
                  <textarea
                    id="recovery-suggestion"
                    value={suggestion}
                    onChange={(event) => setSuggestion(event.target.value)}
                    rows={2}
                    autoFocus
                    placeholder="For example: use a different account, skip this source, or create a new read-only plan…"
                    className="mt-2 w-full resize-none rounded-lg border border-white/10 bg-card/70 px-3 py-2 text-sm outline-none placeholder:text-muted-foreground/50 focus:border-primary/50"
                  />
                  <div className="mt-2 flex justify-end gap-2">
                    <Button size="sm" variant="ghost" onClick={() => setShowSuggestion(false)} disabled={busy}>
                      Cancel
                    </Button>
                    <Button size="sm" onClick={submitSuggestion} disabled={busy || !suggestion.trim()}>
                      Build revised plan
                    </Button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

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
                <Trash2 className="h-3.5 w-3.5" />
                Cancel saved run
              </button>
            )}
          </div>
        </div>
      </div>
    </motion.section>
  );
}
