import { useState, useEffect, useMemo, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Loader2, Layers } from "lucide-react";
import { aura } from "@/api/auraClient";
import { listPythonRuns } from "@/lib/auraApi";
import {
  backendRunNeedsSync,
  backendRunHistoryProjection,
  isExecutedBackendRun,
  upsertHistoryRecord,
  WORKFLOW_HISTORY_CHANGED_EVENT,
  workflowForBackendRun,
  workflowRollup,
} from "@/lib/workflowHistory.mjs";
import WorkflowList from "./WorkflowList";
import WorkflowDetail from "./WorkflowDetail";
import HistoryRunDetail from "./HistoryRunDetail";

let reconciliationPromise = null;
let savedHistoryPromise = null;

async function loadSavedHistory() {
  if (!savedHistoryPromise) {
    savedHistoryPromise = Promise.all([
      aura.entities.Workflow.list("-created_date", 50).catch(() => []),
      aura.entities.WorkflowRun.list("-created_date", 100).catch(() => []),
      aura.entities.Schedule.list("-created_date", 50).catch(() => []),
    ]).then(([workflows, runs, schedules]) => ({ workflows, runs, schedules }))
      .finally(() => {
        savedHistoryPromise = null;
      });
  }
  return savedHistoryPromise;
}

async function reconcileDurableHistory(initialWorkflows, initialRuns) {
  if (reconciliationPromise) return reconciliationPromise;
  reconciliationPromise = (async () => {
    let workflows = initialWorkflows;
    let runs = initialRuns;
    const backendRuns = await listPythonRuns({ limit: 100 }).catch(() => []);
    const executedRuns = backendRuns
      .filter(isExecutedBackendRun)
      .sort((a, b) => Date.parse(a.created_at || 0) - Date.parse(b.created_at || 0));
    let historyChanged = false;

    for (const backendRun of executedRuns) {
      const projection = backendRunHistoryProjection(backendRun);
      let savedRun = runs.find((run) => run.backend_run_id === backendRun.id);
      let workflow = savedRun
        ? workflows.find((item) => item.id === savedRun.workflow_id)
        : workflowForBackendRun(backendRun, workflows);
      try {
        if (!workflow) {
          workflow = await aura.entities.Workflow.create({
            ...projection.workflow,
            run_count: 0,
          });
          workflows = upsertHistoryRecord(workflows, workflow);
        }
        const runData = { ...projection.run, workflow_id: workflow.id };
        if (savedRun && !backendRunNeedsSync(savedRun, runData)) continue;
        savedRun = savedRun
          ? await aura.entities.WorkflowRun.update(savedRun.id, runData)
          : await aura.entities.WorkflowRun.create(runData);
        runs = upsertHistoryRecord(runs, savedRun);
        historyChanged = true;
      } catch (error) {
        console.warn("Could not synchronize durable workflow history", error);
      }
    }

    if (historyChanged) {
      const updatedWorkflows = await Promise.all(workflows.map(async (workflow) => {
        const rollup = workflowRollup(workflow.id, runs);
        if (rollup.run_count === 0) return workflow;
        try {
          return await aura.entities.Workflow.update(workflow.id, rollup);
        } catch (error) {
          console.warn("Could not update saved workflow summary", error);
          return workflow;
        }
      }));
      workflows = updatedWorkflows;
    }

    const orphaned = runs.filter((run) => !run.workflow_id);
    if (orphaned.length > 0) {
      const groups = {};
      orphaned.forEach((run) => { (groups[run.prompt] = groups[run.prompt] || []).push(run); });
      for (const prompt of Object.keys(groups)) {
        const group = groups[prompt].sort((a, b) => new Date(b.created_date) - new Date(a.created_date));
        const latest = group[0];
        try {
          const workflow = await aura.entities.Workflow.create({
            name: (prompt || "Workflow").slice(0, 60),
            prompt,
            interpretation: latest.summary || prompt,
            steps: latest.steps || [],
            last_run_status: latest.status,
            last_run_date: latest.created_date,
            last_summary: latest.summary,
            run_count: group.length,
          });
          await aura.entities.WorkflowRun.updateMany(
            { id: { $in: group.map((run) => run.id) } },
            { $set: { workflow_id: workflow.id } }
          ).catch(() => {});
        } catch (error) {
          console.warn("Could not adopt earlier workflow history", error);
        }
      }
      const refreshed = await loadSavedHistory();
      workflows = refreshed.workflows;
      runs = refreshed.runs;
    }

    return { workflows, runs };
  })().finally(() => {
    reconciliationPromise = null;
  });
  return reconciliationPromise;
}

export default function HistoryPanel({ open, onClose, onRerun, onEditRun }) {
  const [workflows, setWorkflows] = useState([]);
  const [runs, setRuns] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [selectedWorkflow, setSelectedWorkflow] = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const hasHistorySnapshot = useRef(false);

  useEffect(() => {
    let cancelled = false;
    loadSavedHistory().then((saved) => {
      if (cancelled) return;
      hasHistorySnapshot.current = true;
      setWorkflows(saved.workflows);
      setRuns(saved.runs);
      setSchedules(saved.schedules);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(!hasHistorySnapshot.current);
    (async () => {
      const saved = await loadSavedHistory();
      if (cancelled) return;
      hasHistorySnapshot.current = true;
      setWorkflows(saved.workflows);
      setRuns(saved.runs);
      setSchedules(saved.schedules);
      setLoading(false);

      // Historical repair never blocks the panel. Saved records render first;
      // the durable executor is reconciled quietly afterward.
      const reconciled = await reconcileDurableHistory(saved.workflows, saved.runs);
      if (cancelled) return;
      setWorkflows(reconciled.workflows);
      setRuns(reconciled.runs);
    })();
    return () => { cancelled = true; };
  }, [open]);

  // Live updates
  useEffect(() => {
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
    const handleHistoryChanged = (event) => {
      const { workflow, run } = event.detail || {};
      if (workflow || run) hasHistorySnapshot.current = true;
      if (workflow) {
        setWorkflows((previous) => upsertHistoryRecord(previous, workflow));
        setSelectedWorkflow((previous) => previous?.id === workflow.id ? workflow : previous);
      }
      if (run) {
        setRuns((previous) => upsertHistoryRecord(previous, run));
        setSelectedRun((previous) => previous?.id === run.id ? run : previous);
      }
    };
    window.addEventListener(WORKFLOW_HISTORY_CHANGED_EVENT, handleHistoryChanged);
    return () => {
      unsubWf();
      unsubRun();
      window.removeEventListener(WORKFLOW_HISTORY_CHANGED_EVENT, handleHistoryChanged);
    };
  }, []);

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
