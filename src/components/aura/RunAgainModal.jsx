import { useState, useEffect, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, RefreshCw, Pencil, ArrowRight, ShieldCheck, ChevronRight } from "lucide-react";
import { LEVELS, LABELS } from "@/lib/approvalLevels";

function toolsChain(run) {
  const steps = run?.steps || [];
  const seen = [];
  steps.forEach((s) => {
    if (s.tool && !seen.includes(s.tool)) seen.push(s.tool);
  });
  return seen;
}

export default function RunAgainModal({ open, mode = "rerun", run, runCount = 1, onClose, onConfirm }) {
  const isEdit = mode === "edit";
  const [approval, setApproval] = useState("writes");
  const [editing, setEditing] = useState(true);

  useEffect(() => {
    if (open) {
      setApproval("writes");
      setEditing(true);
    }
  }, [open, isEdit]);

  const chain = useMemo(() => toolsChain(run), [run]);
  const title = run?.title || "Workflow";
  const lastOk = run?.status === "completed" || run?.last_run_status === "completed";

  const handleRun = () => onConfirm?.(run?.prompt, approval);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 6 }}
          transition={{ duration: 0.16 }}
          className="rounded-xl border border-white/10 bg-card/60 overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-white/6">
            {isEdit ? <Pencil className="w-3.5 h-3.5 text-primary" /> : <RefreshCw className="w-3.5 h-3.5 text-primary" />}
            <h3 className="text-xs font-semibold">{isEdit ? "Edit & run again" : "Run again?"}</h3>
            <button
              onClick={onClose}
              className="ml-auto p-1 rounded-lg hover:bg-white/8 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="p-3.5 space-y-3">
            {/* Workflow identity */}
            <div>
              <p className="text-xs font-medium leading-snug">{title}</p>
              {chain.length > 0 && (
                <p className="text-[11px] text-muted-foreground/70 mt-1">Uses: {chain.join(" → ")}</p>
              )}
              <div className="flex items-center gap-1.5 mt-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${lastOk ? "bg-emerald-400" : "bg-muted-foreground/40"}`} />
                <span className="text-[11px] text-muted-foreground/70">
                  Last run: {lastOk ? "Successful" : "Not completed"}
                </span>
              </div>
            </div>

            {/* Approval setting */}
            <div>
                <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Approval</label>
                <AnimatePresence mode="wait">
                  {!editing ? (
                    <motion.div
                      key="summary"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="mt-1.5 flex items-center gap-2.5 p-2.5 rounded-lg border border-white/8 bg-card/30"
                    >
                      <ShieldCheck className="w-3.5 h-3.5 text-accent flex-shrink-0" />
                      <span className="text-xs">{LABELS[approval]}</span>
                      <button
                        onClick={() => setEditing(true)}
                        className="ml-auto flex items-center gap-0.5 text-[11px] text-primary hover:text-primary/80 transition-colors"
                      >
                        Change
                        <ChevronRight className="w-3 h-3" />
                      </button>
                    </motion.div>
                  ) : (
                    <motion.div
                      key="options"
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      className="mt-1.5 space-y-1.5 overflow-hidden"
                    >
                      {LEVELS.map((opt) => {
                        const Icon = opt.icon;
                        const active = approval === opt.value;
                        return (
                          <button
                            key={opt.value}
                            onClick={() => setApproval(opt.value)}
                            className={`w-full text-left flex items-start gap-2.5 p-2.5 rounded-lg border transition-colors ${
                              active ? `${opt.ring} ${opt.bg}` : "border-white/8 bg-card/30 hover:bg-card/50"
                            }`}
                          >
                            <Icon className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${active ? opt.color : "text-muted-foreground"}`} />
                            <div className="flex-1 min-w-0">
                              <span className={`text-xs ${active ? "font-medium" : ""}`}>{opt.title}</span>
                              <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{opt.desc}</p>
                            </div>
                            <span
                              className={`mt-1 w-3.5 h-3.5 rounded-full border flex-shrink-0 flex items-center justify-center ${
                                active ? "border-primary bg-primary" : "border-white/15"
                              }`}
                            >
                              {active && <span className="w-1.5 h-1.5 rounded-full bg-primary-foreground" />}
                            </span>
                          </button>
                        );
                      })}
                      <button
                        onClick={() => setEditing(false)}
                        className="text-[11px] text-muted-foreground hover:text-foreground transition-colors pt-0.5"
                      >
                        Done
                      </button>
                    </motion.div>
                  )}
                </AnimatePresence>
            </div>
          </div>

          {/* Footer */}
          <div className="flex justify-end gap-2 px-3.5 py-2.5 border-t border-white/6">
            <button
              onClick={onClose}
              className="text-xs px-3 py-1.5 rounded-lg border border-white/10 text-muted-foreground hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              onClick={handleRun}
              className="flex items-center gap-1.5 text-xs px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-primary to-accent text-white font-medium"
            >
              {isEdit ? "Edit & run" : "Run again"}
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}