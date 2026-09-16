import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  CirclePause,
  CirclePlay,
  Clock3,
  GitBranch,
  Loader2,
  Octagon,
  Pencil,
  Play,
  Power,
  Radio,
} from "lucide-react";
import ProcessModal from "./ProcessModal";
import {
  createProcessInstance,
  listProcessDefinitions,
  listProcessInstances,
  updateProcessDefinition,
  updateProcessInstance,
} from "@/lib/auraApi";
import { notifyWorkflowError } from "@/lib/auraNotify";
import {
  announceProcessChanged,
  PROCESS_CHANGED_EVENT,
  processStatusLabel,
  processStatusTone,
  processTriggerLabel,
} from "@/lib/processes.mjs";

function formatDate(value) {
  if (!value) return null;
  return new Date(value).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

function TriggerIcon({ type, className = "h-3.5 w-3.5" }) {
  if (type === "event") return <Radio className={className} />;
  if (type === "schedule") return <CalendarClock className={className} />;
  return <Play className={className} />;
}

export default function ProcessPanel() {
  const [processes, setProcesses] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [instances, setInstances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [editingProcess, setEditingProcess] = useState(null);
  const selected = useMemo(
    () => processes.find((process) => process.id === selectedId) || null,
    [processes, selectedId]
  );
  const editSelections = useMemo(
    () => (editingProcess?.stages || []).map((stage) => ({
      workflowId: stage.workflow_id,
      name: stage.name,
      backendRunId: stage.source_run_id,
    })),
    [editingProcess]
  );

  const refresh = useCallback(async () => {
    try {
      const definitions = await listProcessDefinitions();
      setProcesses(definitions);
      if (selectedId) {
        const cases = await listProcessInstances(selectedId);
        setInstances(cases);
      }
      setError("");
    } catch (loadError) {
      setError(loadError?.message || "AURA could not load processes.");
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    refresh();
    const handleChanged = () => refresh();
    window.addEventListener(PROCESS_CHANGED_EVENT, handleChanged);
    const interval = window.setInterval(refresh, 15000);
    return () => {
      window.removeEventListener(PROCESS_CHANGED_EVENT, handleChanged);
      window.clearInterval(interval);
    };
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) {
      setInstances([]);
      return;
    }
    listProcessInstances(selectedId).then(setInstances).catch((loadError) => {
      setError(loadError?.message || "AURA could not load process cases.");
    });
  }, [selectedId]);

  useEffect(() => {
    if (selected?.failure_policy !== "notify") return;
    instances.forEach((instance) => {
      if (instance.status !== "attention" || !instance.state?.notification_required) return;
      const key = `aura_process_notice:${instance.id}:${instance.updated_at}`;
      if (localStorage.getItem(key)) return;
      notifyWorkflowError(selected.name, instance.error_code?.replaceAll("_", " "));
      localStorage.setItem(key, new Date().toISOString());
    });
  }, [instances, selected]);

  const start = async () => {
    if (!selected) return;
    setBusy("start");
    try {
      await createProcessInstance(selected.id, {});
      await refresh();
      announceProcessChanged();
    } catch (actionError) {
      setError(actionError?.message || "AURA could not start this process.");
    } finally {
      setBusy("");
    }
  };

  const toggleEnabled = async () => {
    if (!selected) return;
    setBusy("toggle");
    try {
      const updated = await updateProcessDefinition(selected.id, { enabled: !selected.enabled });
      setProcesses((current) => current.map((item) => item.id === updated.id ? { ...item, ...updated } : item));
      announceProcessChanged({ process: updated });
    } catch (actionError) {
      setError(actionError?.message || "AURA could not update this process.");
    } finally {
      setBusy("");
    }
  };

  const act = async (instanceId, action) => {
    setBusy(`${instanceId}:${action}`);
    try {
      const updated = await updateProcessInstance(instanceId, action);
      setInstances((current) => current.map((item) => item.id === updated.id ? updated : item));
      await refresh();
      announceProcessChanged();
    } catch (actionError) {
      setError(actionError?.message || `AURA could not ${action} this case.`);
    } finally {
      setBusy("");
    }
  };

  if (loading) {
    return <div className="flex h-32 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>;
  }

  if (!selected) {
    return (
      <div className="p-4">
        <div className="mb-4 flex items-center gap-5">
          <div><p className="text-lg font-semibold leading-none">{processes.length}</p><p className="mt-1 text-[10px] text-muted-foreground/60">Business processes</p></div>
          <div><p className="text-lg font-semibold leading-none text-primary">{processes.filter((item) => item.enabled).length}</p><p className="mt-1 text-[10px] text-muted-foreground/60">Active</p></div>
          <div><p className="text-lg font-semibold leading-none text-emerald-400">{processes.reduce((sum, item) => sum + (item.completed_instances || 0), 0)}</p><p className="mt-1 text-[10px] text-muted-foreground/60">Cases completed</p></div>
        </div>
        {error && <p className="mb-3 rounded-lg border border-red-400/15 bg-red-400/5 p-2.5 text-xs text-red-300">{error}</p>}
        {processes.length === 0 ? (
          <div className="py-16 text-center">
            <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/8 text-primary"><GitBranch className="h-5 w-5" /></div>
            <p className="mt-4 text-sm font-medium">No processes yet</p>
            <p className="mx-auto mt-1 max-w-xs text-xs leading-relaxed text-muted-foreground">Open the Workflows tab, choose Build a process, and select at least two approved workflows.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {processes.map((process) => (
              <button key={process.id} onClick={() => setSelectedId(process.id)} className="w-full rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5 text-left transition-colors hover:border-primary/20 hover:bg-primary/[0.04]">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><GitBranch className="h-4 w-4" /></div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2"><p className="truncate text-sm font-medium">{process.name}</p><span className={`h-1.5 w-1.5 shrink-0 rounded-full ${process.enabled ? "bg-emerald-400" : "bg-muted-foreground/40"}`} /></div>
                    <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">{process.objective}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground/70">
                      <span className="inline-flex items-center gap-1"><TriggerIcon type={process.trigger?.type} /> {processTriggerLabel(process)}</span>
                      <span>{process.stages?.length || 0} stages</span>
                      {process.active_instances > 0 && <span className="text-primary">{process.active_instances} active</span>}
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <>
    <div>
      <div className="border-b border-white/6 p-4">
        <button onClick={() => setSelectedId(null)} className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" /> All processes</button>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0"><h3 className="text-base font-semibold">{selected.name}</h3><p className="mt-1 text-xs leading-relaxed text-muted-foreground">{selected.objective}</p></div>
          <span className={`shrink-0 rounded-full border px-2 py-1 text-[10px] ${selected.enabled ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-400" : "border-white/10 text-muted-foreground"}`}>{selected.enabled ? "Active" : "Off"}</span>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
          <span className="inline-flex items-center gap-1 rounded-full border border-white/8 px-2 py-1"><TriggerIcon type={selected.trigger?.type} /> {processTriggerLabel(selected)}</span>
          <span className="rounded-full border border-white/8 px-2 py-1">{selected.stages?.length || 0} stages</span>
          <span className="rounded-full border border-white/8 px-2 py-1">Approval: {selected.approval_mode}</span>
          <span className="rounded-full border border-white/8 px-2 py-1">On failure: {selected.failure_policy || "pause"}</span>
        </div>
        {selected.next_trigger_at && <p className="mt-2 text-[10px] text-muted-foreground/70">Next start: {formatDate(selected.next_trigger_at)}</p>}
        <div className="mt-4 grid grid-cols-3 gap-2">
          <button onClick={start} disabled={!selected.enabled || busy === "start"} className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-primary to-accent px-3 py-2 text-xs font-medium text-white disabled:opacity-40">{busy === "start" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />} Start a case</button>
          <button onClick={toggleEnabled} disabled={busy === "toggle"} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs text-muted-foreground hover:bg-white/5"><Power className="h-3.5 w-3.5" /> {selected.enabled ? "Turn off new starts" : "Turn on"}</button>
          <button onClick={() => setEditingProcess(selected)} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs text-muted-foreground hover:bg-white/5"><Pencil className="h-3.5 w-3.5" /> Edit</button>
        </div>
      </div>

      <div className="p-4">
        <p className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground/60">Stages</p>
        <div className="mb-5 space-y-1.5">
          {(selected.stages || []).map((stage, index) => (
            <div key={stage.key} className="rounded-lg border border-white/[0.06] px-3 py-2.5"><div className="flex items-center gap-2.5"><span className="flex h-5 w-5 items-center justify-center rounded-md bg-primary/10 text-[10px] font-semibold text-primary">{index + 1}</span><span className="min-w-0 flex-1 truncate text-xs">{stage.name}</span>{stage.start_on_event && <span className="inline-flex items-center gap-1 text-[9px] text-muted-foreground"><Radio className="h-3 w-3" /> {stage.start_on_event}</span>}{stage.wait_seconds > 0 && <span className="inline-flex items-center gap-1 text-[9px] text-muted-foreground"><Clock3 className="h-3 w-3" /> wait</span>}</div>{stage.context_instructions && <p className="ml-7 mt-1.5 line-clamp-2 text-[9px] leading-relaxed text-muted-foreground/65">{stage.context_instructions}</p>}</div>
          ))}
        </div>

        <p className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground/60">Cases</p>
        {error && <p className="mb-3 rounded-lg border border-red-400/15 bg-red-400/5 p-2.5 text-xs text-red-300">{error}</p>}
        {instances.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/10 py-8 text-center"><p className="text-xs text-muted-foreground">No cases have started yet.</p></div>
        ) : (
          <div className="space-y-2.5">
            {instances.map((instance) => (
              <div key={instance.id} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5">
                <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="truncate text-xs font-medium">{instance.subject_key}</p><p className="mt-1 text-[10px] text-muted-foreground">Stage {instance.current_stage_index + 1}: {instance.current_stage_name || instance.current_stage_key}</p></div><span className={`shrink-0 rounded-full border px-2 py-1 text-[9px] ${processStatusTone(instance.status)}`}>{processStatusLabel(instance.status)}</span></div>
                {instance.status === "waiting_event" && <p className="mt-2 rounded-lg bg-primary/5 px-2.5 py-2 text-[10px] text-muted-foreground">Waiting for <span className="text-primary">{instance.state?.awaiting_event_type}</span></p>}
                {instance.error_code && <p className="mt-2 text-[10px] text-amber-300">{instance.error_code.replaceAll("_", " ")}{instance.state?.notification_required ? " · notification raised" : ""}</p>}
                {instance.stage_runs?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">{instance.stage_runs.map((receipt) => <span key={receipt.id} className="inline-flex items-center gap-1 rounded-full border border-white/[0.07] px-2 py-1 text-[9px] text-muted-foreground"><CheckCircle2 className={`h-2.5 w-2.5 ${receipt.status === "completed" ? "text-emerald-400" : "text-primary"}`} /> {receipt.stage_key}: {receipt.status}</span>)}</div>
                )}
                {instance.next_wake_at && <p className="mt-2 text-[9px] text-muted-foreground/60">Continues {formatDate(instance.next_wake_at)}</p>}
                <div className="mt-3 flex justify-end gap-1.5">
                  {["pending", "waiting", "waiting_event", "running"].includes(instance.status) && <button onClick={() => act(instance.id, "pause")} disabled={busy.startsWith(instance.id)} className="inline-flex items-center gap-1 rounded-lg border border-white/8 px-2.5 py-1.5 text-[10px] text-muted-foreground hover:bg-white/5"><CirclePause className="h-3 w-3" /> Pause</button>}
                  {instance.status === "paused" && <button onClick={() => act(instance.id, "resume")} disabled={busy.startsWith(instance.id)} className="inline-flex items-center gap-1 rounded-lg border border-primary/20 px-2.5 py-1.5 text-[10px] text-primary hover:bg-primary/5"><CirclePlay className="h-3 w-3" /> Resume</button>}
                  {!['completed', 'stopped'].includes(instance.status) && <button onClick={() => act(instance.id, "stop")} disabled={busy.startsWith(instance.id)} className="inline-flex items-center gap-1 rounded-lg border border-red-400/10 px-2.5 py-1.5 text-[10px] text-muted-foreground hover:bg-red-400/5 hover:text-red-300"><Octagon className="h-3 w-3" /> Stop</button>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
    <ProcessModal
      open={Boolean(editingProcess)}
      onClose={() => setEditingProcess(null)}
      selectedWorkflows={editSelections}
      existingProcess={editingProcess}
      onCreated={async () => {
        setEditingProcess(null);
        await refresh();
      }}
    />
    </>
  );
}
