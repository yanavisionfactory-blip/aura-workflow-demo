import { useState, useEffect, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Loader2, Layers } from "lucide-react";
import { aura } from "@/api/auraClient";
import WorkflowList from "./WorkflowList";
import WorkflowDetail from "./WorkflowDetail";
import HistoryRunDetail from "./HistoryRunDetail";

export default function HistoryPanel({ open, onClose, onRerun, onEditRun }) {
  const [workflows, setWorkflows] = useState([]);
  const [runs, setRuns] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [selectedWorkflow, setSelectedWorkflow] = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    (async () => {
      let [wfs, rs, sch] = await Promise.all([
        aura.entities.Workflow.list("-created_date", 50).catch(() => []),
        aura.entities.WorkflowRun.list("-created_date", 100).catch(() => []),
        aura.entities.Schedule.list("-created_date", 50).catch(() => []),
      ]);

      // Backfill: adopt orphaned runs from before the saved-workflow feature
      const orphaned = rs.filter((r) => !r.workflow_id);
      if (orphaned.length > 0) {
        const groups = {};
        orphaned.forEach((r) => { (groups[r.prompt] = groups[r.prompt] || []).push(r); });
        for (const prompt of Object.keys(groups)) {
          const grp = groups[prompt].sort((a, b) => new Date(b.created_date) - new Date(a.created_date));
          const latest = grp[0];
          try {
            const wf = await aura.entities.Workflow.create({
              name: (prompt || "Workflow").slice(0, 60),
              prompt,
              interpretation: latest.summary || prompt,
              steps: latest.steps || [],
              last_run_status: latest.status,
              last_run_date: latest.created_date,
              last_summary: latest.summary,
              run_count: grp.length,
            });
            await aura.entities.WorkflowRun.updateMany(
              { id: { $in: grp.map((r) => r.id) } },
              { $set: { workflow_id: wf.id } }
            ).catch(() => {});
          } catch (e) { /* ignore */ }
        }
        wfs = await aura.entities.Workflow.list("-created_date", 50).catch(() => wfs);
        rs = await aura.entities.WorkflowRun.list("-created_date", 100).catch(() => rs);
      }

      setWorkflows(wfs);
      setRuns(rs);
      setSchedules(sch);
      setLoading(false);
    })();
  }, [open]);

  // Live updates
  useEffect(() => {
    if (!open) return;
    const unsubWf = aura.entities.Workflow.subscribe((event) => {
      if (event.type === "create") setWorkflows((p) => [event.data, ...p]);
      else if (event.type === "update") {
        setWorkflows((p) => p.map((w) => (w.id === event.id ? event.data : w)));
        setSelectedWorkflow((prev) => (prev?.id === event.id ? event.data : prev));
      }
    });
    const unsubRun = aura.entities.WorkflowRun.subscribe((event) => {
      if (event.type === "create") setRuns((p) => [event.data, ...p]);
      else if (event.type === "update") {
        setRuns((p) => p.map((r) => (r.id === event.id ? event.data : r)));
        setSelectedRun((prev) => (prev?.id === event.id ? event.data : prev));
      }
    });
    return () => { unsubWf(); unsubRun(); };
  }, [open]);

  const scheduledPrompts = useMemo(
    () => new Set(schedules.map((s) => s.prompt).filter(Boolean)),
    [schedules]
  );

  const handleWfRerun = (wf, approval) => { onClose(); onRerun(wf, approval); };
  const handleWfEdit = (wf, approval) => { onClose(); onEditRun(wf, approval); };

  const selectedWf = workflows.find((w) => w.id === selectedRun?.workflow_id) || null;

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
          />
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="fixed right-0 top-0 h-full w-full max-w-md z-50 bg-card border-l border-white/6 flex flex-col shadow-2xl"
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-white/6">
              <div className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-primary" />
                <span className="font-semibold text-sm">My workflows</span>
              </div>
              <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-foreground transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto">
              {loading ? (
                <div className="flex items-center justify-center h-32">
                  <Loader2 className="w-5 h-5 text-muted-foreground animate-spin" />
                </div>
              ) : selectedRun ? (
                <HistoryRunDetail
                  run={selectedRun}
                  workflow={selectedWf}
                  runCount={runs.filter((r) => r.workflow_id === selectedRun.workflow_id).length}
                  onBack={() => setSelectedRun(null)}
                  onRerun={async (approval) => {
                    let wf = selectedWf;
                    if (!wf && selectedRun.workflow_id) {
                      try { wf = await aura.entities.Workflow.get(selectedRun.workflow_id); } catch (e) { wf = null; }
                    }
                    onClose();
                    onRerun(wf, approval);
                  }}
                  onEditRun={async (approval) => {
                    let wf = selectedWf;
                    if (!wf && selectedRun.workflow_id) {
                      try { wf = await aura.entities.Workflow.get(selectedRun.workflow_id); } catch (e) { wf = null; }
                    }
                    onClose();
                    onEditRun(wf, approval);
                  }}
                />
              ) : selectedWorkflow ? (
                <WorkflowDetail
                  workflow={selectedWorkflow}
                  runs={runs}
                  onBack={() => setSelectedWorkflow(null)}
                  onOpenRun={(r) => setSelectedRun(r)}
                  onRerun={handleWfRerun}
                  onEditRun={handleWfEdit}
                />
              ) : (
                <>
                  {workflows.length > 0 && <StatsHeader workflows={workflows} />}
                  <WorkflowList workflows={workflows} scheduledPrompts={scheduledPrompts} onSelect={(wf) => setSelectedWorkflow(wf)} />
                </>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function StatsHeader({ workflows }) {
  const total = workflows.length;
  const ok = workflows.filter((w) => w.last_run_status === "completed").length;
  return (
    <div className="px-4 pt-3 pb-1 flex items-center gap-5">
      <div>
        <p className="text-lg font-semibold leading-none">{total}</p>
        <p className="text-[10px] text-muted-foreground/60 mt-1">Saved workflows</p>
      </div>
      {total > 0 && (
        <div>
          <p className="text-lg font-semibold leading-none text-emerald-400">{ok}</p>
          <p className="text-[10px] text-muted-foreground/60 mt-1">Last run successful</p>
        </div>
      )}
    </div>
  );
}
