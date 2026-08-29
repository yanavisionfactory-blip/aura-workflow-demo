import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight, FileCheck2 } from "lucide-react";
import { LEVELS, LABELS } from "@/lib/approvalLevels";

export default function ApprovalPicker({ value, onChange }) {
  const [editing, setEditing] = useState(false);
  const current = LABELS[value] || LABELS.writes;

  return (
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
            <FileCheck2 className="w-3.5 h-3.5 text-accent flex-shrink-0" />
            <span className="text-xs">{current}</span>
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
              const active = value === opt.value;
              return (
                <button
                  key={opt.value}
                  onClick={() => onChange?.(opt.value)}
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
  );
}