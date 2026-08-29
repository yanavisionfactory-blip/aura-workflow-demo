import { useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, RefreshCw, ArrowRight, ShieldAlert } from "lucide-react";
import ApprovalPicker from "./ApprovalPicker";

function toolsChain(run) {
  const seen = [];
  (run?.steps || []).forEach((s) => {
    if (s.tool && !seen.includes(s.tool)) seen.push(s.tool);
  });
  return seen;
}

export default function EditRunReviewModal({ open, run, approval, onApprovalChange, flag, onClose, onRun }) {
  const chain = useMemo(() => toolsChain(run), [run]);
  const title = run?.title || "Workflow";

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
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="fixed bottom-0 right-0 z-50 w-full max-w-md pointer-events-auto"
          >
            <div className="bg-card border border-white/10 rounded-t-2xl shadow-2xl overflow-hidden">
              <div className="flex justify-center pt-2.5 pb-1">
                <div className="w-9 h-1 rounded-full bg-white/15" />
              </div>
              <div className="flex items-center gap-2 px-5 py-4 border-b border-white/6">
                <RefreshCw className="w-4 h-4 text-primary" />
                <h3 className="text-sm font-semibold">Ready to run again?</h3>
                <button
                  onClick={onClose}
                  className="ml-auto p-1.5 rounded-lg hover:bg-white/8 text-muted-foreground hover:text-foreground transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="p-5 space-y-4">
                <div>
                  <p className="text-sm font-medium leading-snug">{title}</p>
                  {chain.length > 0 && (
                    <p className="text-[11px] text-muted-foreground/70 mt-1">Uses: {chain.join(" → ")}</p>
                  )}
                </div>

                {flag && (
                  <div className="flex items-start gap-2 p-2.5 rounded-xl bg-amber-400/[0.06] border border-amber-400/25">
                    <ShieldAlert className="w-3.5 h-3.5 text-amber-400 flex-shrink-0 mt-0.5" />
                    <p className="text-[11px] text-amber-100/90 leading-relaxed">{flag.message}</p>
                  </div>
                )}

                <ApprovalPicker value={approval} onChange={onApprovalChange} />
              </div>

              <div className="flex justify-end gap-2 px-5 py-4 border-t border-white/6">
                <button
                  onClick={onClose}
                  className="text-xs px-3 py-2 rounded-lg border border-white/10 text-muted-foreground hover:bg-white/5"
                >
                  Cancel
                </button>
                <button
                  onClick={onRun}
                  className="flex items-center gap-1.5 text-xs px-4 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700 text-white font-medium"
                >
                  Run with changes
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}