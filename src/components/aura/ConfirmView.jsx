import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, Check, Pencil, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { base44 } from "@/api/base44Client";

export default function ConfirmView({ interpretation, originalPrompt, loading, onConfirm, onEdit }) {
  const [text, setText] = useState(interpretation || "");
  const [adjusting, setAdjusting] = useState(false);
  const [altLoading, setAltLoading] = useState(false);
  const [alternatives, setAlternatives] = useState([]);

  // Sync AURA's interpretation once it arrives (custom prompts mount the view
  // before the LLM response comes back).
  useEffect(() => {
    if (!loading && interpretation) {
      setText(interpretation);
      setAdjusting(false);
    }
  }, [loading, interpretation]);

  // When the user chooses to adjust, surface AI alternative readings they
  // can pick instead of retyping from scratch.
  useEffect(() => {
    if (!adjusting) { setAlternatives([]); return; }
    if (!originalPrompt) return;
    let cancelled = false;
    setAltLoading(true);
    base44.integrations.Core.InvokeLLM({
      prompt: `You are AURA, an AI workflow automation platform. A user wants to automate a workflow.

Original request: "${originalPrompt}"
Current interpretation: "${interpretation}"

Generate TWO DIFFERENT, plausible alternative interpretations of what the user might want — each a clear, conversational sentence in plain business language, meaningfully different in scope, output, or approach from the current one AND from each other. Not rephrasings of the same idea.

Return a JSON object: { "interpretations": ["alternative A", "alternative B"] }.`,
      response_json_schema: { type: "object", properties: { interpretations: { type: "array", items: { type: "string" } } } },
    }).then((res) => {
      if (cancelled) return;
      setAlternatives((res.interpretations || []).filter(Boolean).slice(0, 2));
      setAltLoading(false);
    }).catch(() => {
      if (cancelled) return;
      setAlternatives([]);
      setAltLoading(false);
    });
    return () => { cancelled = true; };
  }, [adjusting, originalPrompt, interpretation]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.4 }}
      className="w-full max-w-2xl mx-auto"
    >
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 rounded-xl bg-primary/10 border border-primary/20">
          <Sparkles className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">Is this what you meant?</h2>
          <p className="text-xs text-muted-foreground">Before I put a plan together, let me make sure I've got this right.</p>
        </div>
      </div>

      {/* Original prompt */}
      <div className="mb-4 p-3 rounded-xl bg-card/40 border border-white/6">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground/50">You said</span>
        <p className="text-sm text-muted-foreground mt-1">{originalPrompt}</p>
      </div>

      {/* AURA's understanding — statement by default, editable when adjusting */}
      <div className="p-4 rounded-xl bg-primary/5 border border-primary/15">
        <div className="flex items-center gap-2 mb-2">
          <Sparkles className="w-4 h-4 text-primary" />
          <span className="text-[10px] uppercase tracking-wider text-primary/70 font-medium">
            Here's what I think you want to do
          </span>
        </div>
        {loading ? (
          <div className="space-y-2">
            <div className="h-3 rounded bg-white/5 animate-pulse" />
            <div className="h-3 rounded bg-white/5 animate-pulse w-5/6" />
            <div className="h-3 rounded bg-white/5 animate-pulse w-4/6" />
          </div>
        ) : adjusting ? (
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            autoFocus
            rows={3}
            className="w-full bg-card/70 border border-primary/20 rounded-lg px-3 py-2 text-sm leading-relaxed outline-none focus:border-primary/40 resize-none placeholder:text-muted-foreground/40"
            placeholder="Describe what AURA should do…"
          />
        ) : (
          <p className="text-sm leading-relaxed text-foreground/90">{interpretation}</p>
        )}
      </div>

      {/* Actions — simple Yes / No, edit-on-demand */}
      <AnimatePresence mode="wait">
        {!adjusting ? (
          <motion.div
            key="yesno"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="flex flex-col sm:flex-row gap-2 mt-6"
          >
            <motion.div whileHover={{ scale: 1.01 }} whileTap={{ scale: 0.99 }} className="flex-1">
              <Button
                size="sm"
                onClick={() => onConfirm(interpretation)}
                disabled={loading}
                className="w-full bg-gradient-to-r from-primary to-primary/80 text-primary-foreground gap-1.5"
              >
                <Check className="w-3.5 h-3.5" />
                Yes, that's right
              </Button>
            </motion.div>
            <motion.div whileHover={{ scale: 1.01 }} whileTap={{ scale: 0.99 }} className="flex-1">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setAdjusting(true)}
                disabled={loading}
                className="w-full border-white/10 hover:bg-white/5 gap-1.5"
              >
                <Pencil className="w-3.5 h-3.5" />
                No, let me adjust
              </Button>
            </motion.div>
          </motion.div>
        ) : (
          <motion.div
            key="adjust"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="mt-6 space-y-3"
          >
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground/50 mb-2">Not quite? Pick a different reading or type your own</p>
              <div className="space-y-1.5 mb-3">
                {altLoading ? (
                  <>
                    <div className="h-9 rounded-lg bg-white/5 animate-pulse" />
                    <div className="h-9 rounded-lg bg-white/5 animate-pulse w-5/6" />
                  </>
                ) : alternatives.length > 0 ? (
                  alternatives.map((alt, i) => {
                    const active = text.trim() === alt.trim();
                    return (
                      <button
                        key={i}
                        type="button"
                        onClick={() => setText(alt)}
                        className={`w-full text-left p-2.5 rounded-lg border text-sm leading-snug transition-all ${
                          active
                            ? "border-primary/50 bg-primary/10 text-foreground"
                            : "border-white/8 bg-card/40 text-muted-foreground hover:bg-card/70 hover:border-white/15"
                        }`}
                      >
                        <span className="text-[10px] uppercase tracking-wider text-primary/60 mr-1.5 font-medium">{i === 0 ? "A" : "B"}</span>
                        {alt}
                      </button>
                    );
                  })
                ) : null}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
                <Button
                  size="sm"
                  onClick={() => onConfirm(text.trim() || interpretation)}
                  disabled={!text.trim()}
                  className="bg-gradient-to-r from-primary to-primary/80 text-primary-foreground gap-1.5"
                >
                  <Check className="w-3.5 h-3.5" />
                  Build the plan
                </Button>
              </motion.div>
              <Button
                size="sm"
                variant="ghost"
                onClick={onEdit}
                className="text-muted-foreground hover:text-foreground gap-1.5"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                Start over
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}