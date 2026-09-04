import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, Pencil, Check, X, RefreshCw, Clock, ChevronRight } from "lucide-react";
import { aura } from "@/api/auraClient";
import { formatDistanceToNow, format } from "date-fns";
import RunAgainModal from "./RunAgainModal";

const runStatusConfig = {
  completed: { color: "text-emerald-400", dot: "bg-emerald-400", label: "Completed" },
  running:   { color: "text-accent",       dot: "bg-accent",      label: "Running" },
  failed:    { color: "text-red-400",      dot: "bg-red-400",     label: "Needs attention" },
};

export default function WorkflowDetail({ workflow, runs, onBack, onOpenRun, onRerun, onEditRun }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(workflow.name || "");
  const [modalMode, setModalMode] = useState(null);

  const handleSave = async () => {
    const n = name.trim();
    if (!n || n === workflow.name) { setEditing(false); setName(workflow.name || ""); return; }
    try { await aura.entities.Workflow.update(workflow.id, { name: n }); } catch (e) { /* ignore */ }
    setEditing(false);
  };

  const wfRuns = runs
    .filter((r) => r.workflow_id === workflow.id)
    .sort((a, b) => new Date(b.created_date) - new Date(a.created_date));

  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="flex flex-col h-full">
      <div className="px-4 pt-4 pb-3 border-b border-white/5">
        <button onClick={onBack} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mb-3">
          <ArrowLeft className="w-3.5 h-3.5" /> Back to workflows
        </button>
        {editing ? (
          <div className="flex items-center gap-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSave(); if (e.key === "Escape") { setEditing(false); setName(workflow.name || ""); } }}
              autoFocus
              className="flex-1 bg-card/70 border border-primary/30 rounded-lg px-2.5 py-1.5 text-sm font-semibold outline-none focus:border-primary/50"
            />
            <button onClick={handleSave} className="p-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
              <Check className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => { setEditing(false); setName(workflow.name || ""); }} className="p-1.5 rounded-lg border border-white/10 text-muted-foreground hover:text-foreground transition-colors">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold leading-snug">{workflow.name || "Workflow"}</h2>
            <button onClick={() => { setName(workflow.name || ""); setEditing(true); }} className="p-1 rounded-lg text-muted-foreground/50 hover:text-foreground hover:bg-white/5 transition-colors" title="Rename workflow">
              <Pencil className="w-3 h-3" />
            </button>
          </div>
        )}
        <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">{workflow.interpretation || workflow.prompt}</p>
        <div className="flex items-center gap-2 mt-2 text-[11px] text-muted-foreground/60">
          <span>{workflow.run_count || wfRuns.length || 0} runs</span>
          {workflow.last_run_date && (
            <>
              <span>•</span>
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" /> Last run {formatDistanceToNow(new Date(workflow.last_run_date), { addSuffix: true })}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground/50 font-medium mb-2">Run history</p>
          {wfRuns.length === 0 ? (
            <p className="text-xs text-muted-foreground/50 px-1">No runs recorded yet.</p>
          ) : (
            <div className="space-y-1.5">
              {wfRuns.map((run) => {
                const cfg = runStatusConfig[run.status] || runStatusConfig.completed;
                const primary = run.metrics?.length
                  ? run.metrics.map((m) => `${m.value} ${m.label}`).join(" · ")
                  : (run.summary || run.title || run.prompt?.slice(0, 50));
                const dur = run.duration_seconds != null
                  ? (run.duration_seconds < 60 ? `${run.duration_seconds.toFixed(1)}s` : `${Math.floor(run.duration_seconds / 60)}m ${Math.round(run.duration_seconds % 60)}s`)
                  : "";
                return (
                  <button
                    key={run.id}
                    onClick={() => onOpenRun(run)}
                    className="w-full text-left flex items-center gap-3 p-2.5 rounded-lg border border-white/5 bg-card/30 hover:bg-card/60 hover:border-white/10 transition-colors"
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot} flex-shrink-0`} />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium truncate">{primary}</p>
                      <p className="text-[11px] text-muted-foreground/60 mt-0.5 truncate">
                        {format(new Date(run.created_date), "MMM d, h:mm a")}{dur ? ` · ${dur}` : ""} · <span className={cfg.color}>{cfg.label}</span>
                      </p>
                    </div>
                    <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/30 flex-shrink-0" />
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="p-4 border-t border-white/5">
        {modalMode ? (
          <RunAgainModal
            open
            mode={modalMode}
            run={{ prompt: workflow.prompt, title: workflow.name, steps: workflow.steps, status: workflow.last_run_status }}
            runCount={wfRuns.length}
            onClose={() => setModalMode(null)}
            onConfirm={(prompt, approval) => {
              const mode = modalMode;
              setModalMode(null);
              if (mode === "edit") onEditRun(workflow, approval);
              else onRerun(workflow, approval);
            }}
          />
        ) : (
          <div className="flex gap-2">
            <button
              onClick={() => setModalMode("rerun")}
              className="flex-1 flex items-center justify-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-white/10 text-foreground hover:bg-white/5 transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Run again
            </button>
            <button
              onClick={() => setModalMode("edit")}
              className="flex-1 flex items-center justify-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-primary/90 hover:bg-primary text-primary-foreground transition-colors"
            >
              <Pencil className="w-3.5 h-3.5" /> Edit & run
            </button>
          </div>
        )}
      </div>
    </motion.div>
  );
}
