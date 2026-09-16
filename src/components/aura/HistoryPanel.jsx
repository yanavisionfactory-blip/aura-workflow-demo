import { useState, useEffect, useMemo, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, GitBranch, Layers, Loader2, X } from "lucide-react";
import { aura } from "@/api/auraClient";
import {
  deleteWorkflowSchedule,
  getPythonRun,
  listPythonRuns,
  listWorkflowSchedules,
  updateWorkflowSchedule,
} from "@/lib/auraApi";
import { notifyScheduledWorkflow } from "@/lib/auraNotify";
import {
  schedulesForWorkflow,
  WORKFLOW_SCHEDULE_CHANGED_EVENT,
} from "@/lib/workflowSchedule.mjs";
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
import ProcessPanel from "./ProcessPanel";
import ProcessModal from "./ProcessModal";

let reconciliationPromise = null;
let savedHistoryPromise = null;

async function loadSavedHistory() {
  if (!savedHistoryPromise) {
    savedHistoryPromise = Promise.all([
      aura.entities.Workflow.list("-created_date", 50).catch(() => []),
      aura.entities.WorkflowRun.list("-created_date", 100).catch(() => []),
    ]).then(([workflows, runs]) => ({ workflows, runs }))
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
  const [activeTab, setActiveTab] = useState("workflows");
  const [selectingProcess, setSelectingProcess] = useState(false);
  const [selectedProcessWorkflowIds, setSelectedProcessWorkflowIds] = useState([]);
  const [showProcessBuilder, setShowProcessBuilder] = useState(false);
  const [loading, setLoading] = useState(true);
  const hasHistorySnapshot = useRef(false);
  const schedulesRef = useRef([]);
  const observedScheduledRunsRef = useRef(new Set());

  useEffect(() => {
    schedulesRef.current = schedules;
  }, [schedules]);

  useEffect(() => {
    let cancelled = false;
    const attentionStatuses = new Set([
      "awaiting_approval",
      "blocked",
      "cancelled",
      "failed",
      "waiting_for_action",
    ]);
    const checkScheduledRuns = async () => {
      const freshSchedules = await listWorkflowSchedules().catch(() => schedulesRef.current);
      if (cancelled) return;
      schedulesRef.current = freshSchedules;
      setSchedules(freshSchedules);
      let historyNeedsSync = false;
      for (const schedule of freshSchedules) {
        if (!schedule.last_run_id) continue;
        const run = await getPythonRun(schedule.last_run_id).catch(() => null);
        if (cancelled) return;
        if (!run) continue;
        const observationKey = `${run.id}:${run.updated_at}:${run.status}`;
        if (!observedScheduledRunsRef.current.has(observationKey)) {
          observedScheduledRunsRef.current.add(observationKey);
          historyNeedsSync = true;
        }
        const shouldNotify = (run.status === "completed" && schedule.notify_on_completion)
          || (attentionStatuses.has(run.status) && schedule.notify_on_attention);
        if (!shouldNotify) continue;
        const notificationKey = `aura_schedule_notice:${schedule.id}:${run.id}:${run.status}`;
        if (localStorage.getItem(notificationKey)) continue;
        if (notifyScheduledWorkflow(schedule.name, run.status, run.error)) {
          localStorage.setItem(notificationKey, new Date().toISOString());
        }
      }
      if (historyNeedsSync) {
        const snapshot = await loadSavedHistory();
        const reconciled = await reconcileDurableHistory(snapshot.workflows, snapshot.runs);
        if (!cancelled) {
          hasHistorySnapshot.current = true;
          setWorkflows(reconciled.workflows);
          setRuns(reconciled.runs);
        }
      }
    };
    const interval = window.setInterval(checkScheduledRuns, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadSavedHistory().then((saved) => {
      if (cancelled) return;
      hasHistorySnapshot.current = true;
      setWorkflows(saved.workflows);
      setRuns(saved.runs);
      setLoading(false);
    });
    listWorkflowSchedules().then((items) => {
      if (!cancelled) setSchedules(items);
    }).catch(() => {});
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
      setLoading(false);
      listWorkflowSchedules().then((items) => {
        if (!cancelled) setSchedules(items);
      }).catch(() => {});

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
    const handleScheduleChanged = (event) => {
      const { schedule, deletedId } = event.detail || {};
      if (deletedId) {
        setSchedules((previous) => previous.filter((item) => item.id !== deletedId));
      } else if (schedule?.id) {
        setSchedules((previous) => upsertHistoryRecord(previous, schedule));
      }
    };
    window.addEventListener(WORKFLOW_HISTORY_CHANGED_EVENT, handleHistoryChanged);
    window.addEventListener(WORKFLOW_SCHEDULE_CHANGED_EVENT, handleScheduleChanged);
    return () => {
      unsubWf();
      unsubRun();
      window.removeEventListener(WORKFLOW_HISTORY_CHANGED_EVENT, handleHistoryChanged);
      window.removeEventListener(WORKFLOW_SCHEDULE_CHANGED_EVENT, handleScheduleChanged);
    };
  }, []);

  const scheduledPrompts = useMemo(
    () => new Set(
      schedules.filter((schedule) => schedule.enabled)
        .map((schedule) => schedule.workflow_prompt)
        .filter(Boolean)
    ),
    [schedules]
  );
  const scheduledWorkflowIds = useMemo(
    () => new Set(
      schedules.filter((schedule) => schedule.enabled)
        .map((schedule) => schedule.history_workflow_id)
        .filter(Boolean)
    ),
    [schedules]
  );
  const latestProcessRuns = useMemo(() => {
    const byWorkflow = new Map();
    runs
      .filter((run) => run.workflow_id && run.backend_run_id && run.status === "completed")
      .sort((left, right) => Date.parse(right.backend_updated_at || right.updated_date || right.created_date || 0)
        - Date.parse(left.backend_updated_at || left.updated_date || left.created_date || 0))
      .forEach((run) => {
        if (!byWorkflow.has(run.workflow_id)) byWorkflow.set(run.workflow_id, run);
      });
    return byWorkflow;
  }, [runs]);
  const eligibleProcessWorkflowIds = useMemo(
    () => new Set(latestProcessRuns.keys()),
    [latestProcessRuns]
  );
  const processSelections = useMemo(
    () => selectedProcessWorkflowIds.map((workflowId) => {
      const workflow = workflows.find((item) => item.id === workflowId);
      const run = latestProcessRuns.get(workflowId);
      return workflow && run ? {
        workflowId,
        name: workflow.name || workflow.prompt || "Approved workflow",
        prompt: workflow.prompt || "",
        backendRunId: run.backend_run_id,
      } : null;
    }).filter(Boolean),
    [latestProcessRuns, selectedProcessWorkflowIds, workflows]
  );

  const updateSchedule = async (scheduleId, changes) => {
    const updated = await updateWorkflowSchedule(scheduleId, changes);
    setSchedules((previous) => upsertHistoryRecord(previous, updated));
    return updated;
  };

  const deleteSchedule = async (scheduleId) => {
    await deleteWorkflowSchedule(scheduleId);
    setSchedules((previous) => previous.filter((item) => item.id !== scheduleId));
  };

  const handleWfRerun = (wf, approval) => { onClose(); onRerun(wf, approval); };
  const handleWfEdit = (wf, approval) => { onClose(); onEditRun(wf, approval); };

  const stopProcessSelection = () => {
    setSelectingProcess(false);
    setSelectedProcessWorkflowIds([]);
  };

  const toggleProcessWorkflow = (workflow) => {
    setSelectedProcessWorkflowIds((current) => current.includes(workflow.id)
      ? current.filter((id) => id !== workflow.id)
      : [...current, workflow.id]);
  };

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
              <button onClick={() => { stopProcessSelection(); onClose(); }} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-foreground transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-1 border-b border-white/6 px-4 py-2">
              <button
                type="button"
                onClick={() => setActiveTab("workflows")}
                className={`flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs transition-colors ${activeTab === "workflows" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-white/5"}`}
              >
                <Layers className="h-3.5 w-3.5" /> Workflows
              </button>
              <button
                type="button"
                onClick={() => {
                  setSelectedWorkflow(null);
                  setSelectedRun(null);
                  setActiveTab("processes");
                }}
                className={`flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs transition-colors ${activeTab === "processes" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-white/5"}`}
              >
                <GitBranch className="h-3.5 w-3.5" /> Processes
              </button>
            </div>

            <div className="flex-1 overflow-y-auto">
              {activeTab === "processes" ? (
                <ProcessPanel />
              ) : loading ? (
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
                  schedules={schedulesForWorkflow(schedules, selectedWorkflow)}
                  onBack={() => setSelectedWorkflow(null)}
                  onOpenRun={(r) => setSelectedRun(r)}
                  onRerun={handleWfRerun}
                  onEditRun={handleWfEdit}
                  onUpdateSchedule={updateSchedule}
                  onDeleteSchedule={deleteSchedule}
                />
              ) : (
                <>
                  {workflows.length > 0 && <StatsHeader workflows={workflows} schedules={schedules} />}
                  {workflows.length > 0 && !selectingProcess && (
                    <div className="px-3 pb-1 pt-2">
                      <button
                        type="button"
                        onClick={() => setSelectingProcess(true)}
                        className="flex w-full items-center gap-3 rounded-xl border border-primary/20 bg-primary/[0.055] px-3.5 py-3 text-left transition-colors hover:bg-primary/[0.1]"
                      >
                        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary"><GitBranch className="h-4 w-4" /></span>
                        <span className="min-w-0 flex-1"><span className="block text-sm font-medium text-primary">Build a process</span><span className="mt-0.5 block text-[10px] text-muted-foreground">Select workflows to run one after another.</span></span>
                      </button>
                    </div>
                  )}
                  {selectingProcess && (
                    <div className="sticky top-0 z-10 border-b border-white/6 bg-card/95 px-4 py-3 backdrop-blur">
                      <div className="flex items-center justify-between gap-3">
                        <div><p className="text-xs font-medium">Select workflows</p><p className="mt-0.5 text-[10px] text-muted-foreground">Choose at least two. You can reorder them next.</p></div>
                        <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-1 text-[10px] text-primary">{selectedProcessWorkflowIds.length} selected</span>
                      </div>
                      <div className="mt-3 grid grid-cols-2 gap-2">
                        <button type="button" onClick={stopProcessSelection} className="rounded-lg border border-white/10 px-3 py-2 text-xs text-muted-foreground hover:bg-white/5">Cancel</button>
                        <button
                          type="button"
                          onClick={() => setShowProcessBuilder(true)}
                          disabled={processSelections.length < 2}
                          className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-primary to-accent px-3 py-2 text-xs font-medium text-white disabled:opacity-40"
                        >
                          <Check className="h-3.5 w-3.5" /> Continue
                        </button>
                      </div>
                    </div>
                  )}
                  <WorkflowList
                    workflows={workflows}
                    scheduledPrompts={scheduledPrompts}
                    scheduledWorkflowIds={scheduledWorkflowIds}
                    onSelect={(wf) => setSelectedWorkflow(wf)}
                    selectionMode={selectingProcess}
                    selectedWorkflowIds={new Set(selectedProcessWorkflowIds)}
                    eligibleWorkflowIds={eligibleProcessWorkflowIds}
                    onToggle={toggleProcessWorkflow}
                  />
                </>
              )}
            </div>
          </motion.div>
          <ProcessModal
            open={showProcessBuilder}
            onClose={() => setShowProcessBuilder(false)}
            selectedWorkflows={processSelections}
            onCreated={() => {
              setShowProcessBuilder(false);
              stopProcessSelection();
              setActiveTab("processes");
            }}
          />
        </>
      )}
    </AnimatePresence>
  );
}

function StatsHeader({ workflows, schedules }) {
  const total = workflows.length;
  const ok = workflows.filter((w) => w.last_run_status === "completed").length;
  const activeSchedules = schedules.filter((schedule) => schedule.enabled).length;
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
      {activeSchedules > 0 && (
        <div>
          <p className="text-lg font-semibold leading-none text-primary">{activeSchedules}</p>
          <p className="text-[10px] text-muted-foreground/60 mt-1">Active schedules</p>
        </div>
      )}
    </div>
  );
}
