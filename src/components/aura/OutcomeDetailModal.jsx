import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  MessageSquare,
  Users,
  Mail,
  FileText,
  BarChart3,
  CheckCircle2,
  ExternalLink,
  FileDown,
} from "lucide-react";
import { downloadCSV, safeName } from "@/lib/auraDownload";

const outcomeIcons = {
  message: MessageSquare,
  crm: Users,
  email: Mail,
  document: FileText,
  metric: BarChart3,
};

const typeLabel = {
  message: "Notification",
  crm: "CRM record",
  email: "Email",
  document: "Document",
  metric: "Metric",
};

// Shows the concrete records / people / notifications behind a single outcome.
export default function OutcomeDetailModal({ outcome, open, onClose }) {
  return (
    <AnimatePresence>
      {open && outcome && (
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
            <div className="w-full max-w-lg max-h-[80vh] flex flex-col bg-card border border-white/10 rounded-2xl shadow-2xl pointer-events-auto overflow-hidden">
              <div className="flex items-start gap-3 px-5 py-4 border-b border-white/6">
                {(() => {
                  const Icon = outcomeIcons[outcome.type] || CheckCircle2;
                  return (
                    <div className="p-2 rounded-xl bg-primary/10 flex-shrink-0">
                      <Icon className="w-4 h-4 text-primary" />
                    </div>
                  );
                })()}
                <div className="flex-1 min-w-0">
                  <span className="text-[10px] uppercase tracking-wider text-primary/60 font-medium">
                    {typeLabel[outcome.type] || "Outcome"}
                  </span>
                  <h3 className="text-sm font-semibold leading-snug">{outcome.title}</h3>
                  {outcome.detail && (
                    <p className="text-xs text-muted-foreground mt-0.5">{outcome.detail}</p>
                  )}
                  <div className="mt-2 flex items-center gap-2 flex-wrap">
                    {outcome.link && (
                      <a
                        href={outcome.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-full border border-accent/30 text-accent hover:bg-accent/10 transition-colors"
                      >
                        <ExternalLink className="w-3 h-3" /> {outcome.linkLabel || "Open"}
                      </a>
                    )}
                    {outcome.items && outcome.items.length > 0 && (
                      <button
                        onClick={() =>
                          downloadCSV(
                            `${safeName(outcome.title)}.csv`,
                            ["Label", "Detail"],
                            outcome.items.map((it) => [it.label || "", it.detail || ""])
                          )
                        }
                        className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-full border border-white/10 text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
                      >
                        <FileDown className="w-3 h-3" /> CSV
                      </button>
                    )}
                  </div>
                </div>
                <button
                  onClick={onClose}
                  className="p-1.5 rounded-lg hover:bg-white/8 text-muted-foreground hover:text-foreground transition-colors flex-shrink-0"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-2">
                {outcome.items && outcome.items.length > 0 ? (
                  outcome.items.map((it, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.04 }}
                      className="flex items-start gap-2.5 p-3 rounded-xl border border-white/5 bg-card/40"
                    >
                      <div className="w-1.5 h-1.5 rounded-full bg-primary/60 mt-1.5 flex-shrink-0" />
                      <div className="min-w-0">
                        <p className="text-sm font-medium leading-snug">{it.label}</p>
                        {it.detail && (
                          <p className="text-xs text-muted-foreground mt-0.5">{it.detail}</p>
                        )}
                      </div>
                    </motion.div>
                  ))
                ) : (
                  <p className="text-sm text-muted-foreground">
                    No per-record details available for this item.
                  </p>
                )}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}