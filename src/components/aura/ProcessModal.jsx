import { useEffect, useState } from "react";
import { DragDropContext, Draggable, Droppable } from "@hello-pangea/dnd";
import { AnimatePresence, motion } from "framer-motion";
import {
  BellRing,
  CalendarClock,
  Check,
  Eye,
  FileCheck2,
  GitBranch,
  GripVertical,
  Loader2,
  PauseCircle,
  Play,
  Radio,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { createProcessDefinition, getPythonRun, updateProcessDefinition } from "@/lib/auraApi";
import { announceProcessChanged } from "@/lib/processes.mjs";
import { browserTimezone } from "@/lib/workflowSchedule.mjs";

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const APPROVAL_LEVELS = [
  { value: "review", icon: Eye, label: "Review each workflow", detail: "AURA prepares every stage, then waits for you." },
  { value: "writes", icon: FileCheck2, label: "Ask before external changes", detail: "Research can continue; sends and updates wait for approval." },
  { value: "auto", icon: Zap, label: "Run automatically", detail: "Uses the approved workflows. Safety or access changes still pause it." },
];
const FAILURE_OPTIONS = [
  { value: "pause", icon: PauseCircle, label: "Pause for review", detail: "Stop at the failed workflow and wait for you." },
  { value: "retry", icon: RefreshCw, label: "Retry automatically", detail: "Retry the same approved workflow up to three times, then pause." },
  { value: "notify", icon: BellRing, label: "Stop and notify me", detail: "Stop the process and raise an attention notification." },
];
const TRIGGER_OPTIONS = [
  { value: "manual", icon: Play, label: "Manual" },
  { value: "event", icon: Radio, label: "Business event" },
  { value: "schedule", icon: CalendarClock, label: "Schedule" },
];

function usableRun(run) {
  return run?.status === "completed" && run?.plan_approved && run?.plan?.steps?.length > 0;
}

function runName(run) {
  return run?.historyName || run?.plan?.name || run?.prompt || "Approved workflow";
}

function declaredOutput(run) {
  const contract = run?.plan?.result_contract || {};
  const primary = (run?.plan?.steps || []).find((step) => step.key === contract.primary_step_key)
    || (run?.plan?.steps || []).at(-1);
  const variables = Object.keys(primary?.output_variables || {});
  if (variables.length > 0) return variables.join(", ");
  return primary?.expected_output || `${runName(run)} result`;
}

function transitionProposal(source, target) {
  return `Pass ${declaredOutput(source)} from “${runName(source)}” into “${runName(target)}” as its working context.`;
}

function synchronizeTransitions(orderedRuns, current = {}) {
  const next = {};
  orderedRuns.forEach((run, index) => {
    if (index === 0) return;
    const source = orderedRuns[index - 1];
    const existing = current[run.id];
    next[run.id] = existing?.sourceRunId === source.id
      ? existing
      : { sourceRunId: source.id, text: transitionProposal(source, run) };
  });
  return next;
}

export default function ProcessModal({ open, onClose, selectedWorkflows = [], existingProcess = null, onCreated }) {
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [contextInstructions, setContextInstructions] = useState("");
  const [stages, setStages] = useState([]);
  const [transitionInstructions, setTransitionInstructions] = useState({});
  const [triggerType, setTriggerType] = useState("manual");
  const [eventType, setEventType] = useState("");
  const [cadence, setCadence] = useState("weekly");
  const [dayOfWeek, setDayOfWeek] = useState(1);
  const [dayOfMonth, setDayOfMonth] = useState(1);
  const [time, setTime] = useState("08:00");
  const [approval, setApproval] = useState("writes");
  const [failurePolicy, setFailurePolicy] = useState("pause");
  const [startNow, setStartNow] = useState(false);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [selectionLoadFailed, setSelectionLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const firstName = selectedWorkflows[0]?.name || "Selected workflows";
    const savedTrigger = existingProcess?.trigger || {};
    setName(existingProcess?.name || `${firstName} process`);
    setObjective(existingProcess?.objective || "Coordinate these approved workflows from start to finish.");
    setContextInstructions(existingProcess?.context_instructions || "Keep the same business context throughout the process and use each completed result in the next workflow.");
    setTransitionInstructions({});
    setTriggerType(savedTrigger.type || "manual");
    setEventType(savedTrigger.event_type || "");
    setCadence(savedTrigger.cadence || "weekly");
    setDayOfWeek(savedTrigger.day_of_week ?? 1);
    setDayOfMonth(savedTrigger.day_of_month ?? 1);
    setTime(savedTrigger.local_time || "08:00");
    setApproval(existingProcess?.approval_mode || "writes");
    setFailurePolicy(existingProcess?.failure_policy || "pause");
    setStartNow(false);
    setSaved(null);
    setError("");
    setLoadingRuns(true);
    setSelectionLoadFailed(false);
    Promise.all(selectedWorkflows.map(async (selection) => {
      const run = await getPythonRun(selection.backendRunId).catch(() => null);
      return run ? { ...run, historyName: selection.name, historyWorkflowId: selection.workflowId } : null;
    })).then((loaded) => {
      if (cancelled) return;
      const usable = loaded.filter(usableRun);
      setStages(usable);
      const proposed = synchronizeTransitions(usable);
      const storedTransitions = Object.fromEntries(usable.slice(1).map((run, index) => {
        const stored = existingProcess?.stages?.find((stage) => stage.source_run_id === run.id);
        return [run.id, {
          sourceRunId: usable[index].id,
          text: stored?.context_instructions || proposed[run.id]?.text || "",
        }];
      }));
      setTransitionInstructions(storedTransitions);
      if (usable.length !== selectedWorkflows.length) {
        setSelectionLoadFailed(true);
        setError("One or more selected workflows no longer has a completed, approved run. Return to workflow history and select another workflow.");
      }
      setLoadingRuns(false);
    });
    return () => { cancelled = true; };
  }, [existingProcess, open, selectedWorkflows]);

  const reorderStages = ({ source, destination }) => {
    if (!destination || destination.index === source.index) return;
    setStages((current) => {
      const reordered = [...current];
      const [moved] = reordered.splice(source.index, 1);
      reordered.splice(destination.index, 0, moved);
      setTransitionInstructions((existing) => synchronizeTransitions(reordered, existing));
      return reordered;
    });
  };

  const removeStage = (runId) => {
    setStages((current) => {
      const remaining = current.filter((item) => item.id !== runId);
      setTransitionInstructions((existing) => synchronizeTransitions(remaining, existing));
      return remaining;
    });
  };

  const handleCreate = async () => {
    if (!name.trim() || !objective.trim() || stages.length < 2) {
      setError("Add a name, objective, and at least two approved workflows.");
      return;
    }
    if (triggerType === "event" && !eventType.trim()) {
      setError("Name the business event that should start this process, for example deal.closed.");
      return;
    }
    setSaving(true);
    setError("");
    const trigger = triggerType === "event"
      ? { type: "event", event_type: eventType.trim() }
      : triggerType === "schedule"
        ? {
            type: "schedule",
            cadence,
            timezone: browserTimezone(),
            local_time: time,
            ...(cadence === "weekly" ? { day_of_week: dayOfWeek } : {}),
            ...(cadence === "monthly" ? { day_of_month: dayOfMonth } : {}),
          }
        : { type: "manual" };
    try {
      const payload = {
        name: name.trim(),
        objective: objective.trim(),
        context_instructions: contextInstructions.trim(),
        trigger,
        stages: stages.map((run, index) => ({
          key: `stage_${index + 1}`,
          name: runName(run).slice(0, 200),
          source_run_id: run.id,
          context_instructions: index === 0 ? null : transitionInstructions[run.id]?.text?.trim() || null,
        })),
        approval_mode: approval,
        failure_policy: failurePolicy,
        ...(existingProcess ? {} : { start_immediately: triggerType === "manual" && startNow }),
      };
      const process = existingProcess
        ? await updateProcessDefinition(existingProcess.id, payload)
        : await createProcessDefinition(payload);
      setSaved(process);
      announceProcessChanged({ process });
    } catch (saveError) {
      setError(saveError?.message || "AURA could not create this process.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm" />
          <motion.div initial={{ opacity: 0, scale: 0.96, y: 16 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96, y: 16 }} className="fixed inset-0 z-[60] flex items-center justify-center p-4">
            <div className="pointer-events-auto max-h-[calc(100vh-2rem)] w-full max-w-2xl overflow-y-auto rounded-2xl border border-white/10 bg-card shadow-2xl">
              <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-white/6 bg-card/95 px-5 py-4 backdrop-blur">
                <GitBranch className="h-4 w-4 text-primary" />
                <div><h3 className="text-sm font-semibold">Build a process</h3><p className="mt-0.5 text-[10px] text-muted-foreground">Order selected workflows and define how their context moves forward.</p></div>
                <button type="button" onClick={onClose} className="ml-auto rounded-lg p-1.5 text-muted-foreground hover:bg-white/8 hover:text-foreground" aria-label="Close process builder"><X className="h-4 w-4" /></button>
              </div>

              {saved ? (
                <div className="p-8 text-center">
                  <div className="mb-3 inline-flex rounded-2xl border border-emerald-400/20 bg-emerald-400/10 p-3"><Check className="h-6 w-6 text-emerald-400" /></div>
                  <p className="text-sm font-semibold">{existingProcess ? `${saved.name} was updated` : `${saved.name} is ready`}</p>
                  <p className="mx-auto mt-1 max-w-sm text-xs leading-relaxed text-muted-foreground">{saved.initial_instance ? "The first process case has started through AURA’s normal safety and approval path." : "AURA validated every selected workflow and saved the process under My workflows → Processes."}</p>
                  <button type="button" onClick={() => onCreated?.(saved)} className="mt-5 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground">View process</button>
                </div>
              ) : (
                <div className="space-y-5 p-5">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="block text-[10px] uppercase tracking-wider text-muted-foreground/60">Process name<input value={name} onChange={(event) => setName(event.target.value)} className="mt-1.5 w-full rounded-lg border border-white/8 bg-secondary/40 px-3 py-2 text-sm normal-case tracking-normal outline-none focus:border-primary/40" /></label>
                    <label className="block text-[10px] uppercase tracking-wider text-muted-foreground/60">Process objective<input value={objective} onChange={(event) => setObjective(event.target.value)} className="mt-1.5 w-full rounded-lg border border-white/8 bg-secondary/40 px-3 py-2 text-sm normal-case tracking-normal outline-none focus:border-primary/40" /></label>
                  </div>

                  <section>
                    <div className="flex items-end justify-between gap-3"><div><p className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Ordered workflows</p><p className="mt-1 text-[11px] text-muted-foreground">Drag workflows into the order AURA should run them.</p></div><span className="text-[10px] text-muted-foreground/60">{stages.length} workflows</span></div>
                    {loadingRuns ? (
                      <div className="mt-2 flex items-center justify-center rounded-xl border border-white/8 py-8"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
                    ) : (
                      <DragDropContext onDragEnd={reorderStages}>
                        <Droppable droppableId="process-stages">
                          {(dropProvided) => (
                            <div ref={dropProvided.innerRef} {...dropProvided.droppableProps} className="mt-2 space-y-2">
                              {stages.map((run, index) => (
                                <Draggable key={run.id} draggableId={String(run.id)} index={index}>
                                  {(dragProvided, snapshot) => (
                                    <div ref={dragProvided.innerRef} {...dragProvided.draggableProps} className={snapshot.isDragging ? "rounded-xl shadow-2xl shadow-black/30" : ""}>
                                      <div className="flex items-center gap-3 rounded-xl border border-white/8 bg-card p-3">
                                        <button type="button" {...dragProvided.dragHandleProps} className="cursor-grab rounded-lg p-1 text-muted-foreground/60 hover:bg-white/5 hover:text-foreground" aria-label={`Reorder ${runName(run)}`}><GripVertical className="h-4 w-4" /></button>
                                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-xs font-semibold text-primary">{index + 1}</span>
                                        <div className="min-w-0 flex-1"><p className="truncate text-xs font-medium">{runName(run)}</p><p className="mt-0.5 truncate text-[10px] text-muted-foreground">{run.prompt}</p></div>
                                        {stages.length > 2 && <button type="button" onClick={() => removeStage(run.id)} className="rounded-lg p-1.5 text-muted-foreground hover:bg-red-400/10 hover:text-red-300" aria-label={`Remove ${runName(run)}`}><Trash2 className="h-3.5 w-3.5" /></button>}
                                      </div>
                                      {index > 0 && (
                                        <div className="mx-4 rounded-b-xl border-x border-b border-primary/15 bg-primary/[0.04] p-3">
                                          <p className="mb-1.5 flex items-center gap-1.5 text-[10px] font-medium text-primary"><Sparkles className="h-3 w-3" /> AURA-proposed context</p>
                                          <textarea value={transitionInstructions[run.id]?.text || ""} onChange={(event) => setTransitionInstructions((current) => ({ ...current, [run.id]: { sourceRunId: stages[index - 1].id, text: event.target.value } }))} rows={2} className="w-full resize-none rounded-lg border border-white/8 bg-secondary/30 px-3 py-2 text-xs leading-relaxed text-foreground outline-none focus:border-primary/40" />
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </Draggable>
                              ))}
                              {dropProvided.placeholder}
                            </div>
                          )}
                        </Droppable>
                      </DragDropContext>
                    )}
                  </section>

                  <label className="block text-[10px] uppercase tracking-wider text-muted-foreground/60">Shared process context<textarea value={contextInstructions} onChange={(event) => setContextInstructions(event.target.value)} rows={3} placeholder="For example: keep the same campaign context and only continue with verified leads." className="mt-1.5 w-full resize-none rounded-lg border border-white/8 bg-secondary/40 px-3 py-2 text-xs normal-case leading-relaxed tracking-normal text-foreground outline-none focus:border-primary/40" /></label>

                  <section>
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground/60">What starts it?</p>
                    <div className="mt-2 grid grid-cols-3 gap-1.5">{TRIGGER_OPTIONS.map(({ value, icon: Icon, label }) => <button type="button" key={value} onClick={() => setTriggerType(value)} className={`flex items-center justify-center gap-1.5 rounded-lg border px-2 py-2 text-xs ${triggerType === value ? "border-primary/40 bg-primary/10 text-primary" : "border-white/8 text-muted-foreground hover:bg-white/5"}`}><Icon className="h-3.5 w-3.5" /> {label}</button>)}</div>
                    {triggerType === "event" && <label className="mt-2 block text-[10px] text-muted-foreground">Event name<input value={eventType} onChange={(event) => setEventType(event.target.value)} placeholder="deal.closed" className="mt-1.5 w-full rounded-lg border border-white/8 bg-secondary/40 px-3 py-2 text-xs text-foreground outline-none focus:border-primary/40" /></label>}
                    {triggerType === "schedule" && (
                      <div className="mt-2 grid grid-cols-2 gap-2 rounded-xl border border-white/8 bg-white/[0.02] p-3">
                        <select value={cadence} onChange={(event) => setCadence(event.target.value)} className="rounded-lg border border-white/8 bg-secondary/40 px-2.5 py-2 text-xs"><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select>
                        <input type="time" value={time} onChange={(event) => setTime(event.target.value)} className="rounded-lg border border-white/8 bg-secondary/40 px-2.5 py-2 text-xs" />
                        {cadence === "weekly" && <select value={dayOfWeek} onChange={(event) => setDayOfWeek(Number(event.target.value))} className="col-span-2 rounded-lg border border-white/8 bg-secondary/40 px-2.5 py-2 text-xs">{DAYS.map((day, index) => <option key={day} value={index}>{day}</option>)}</select>}
                        {cadence === "monthly" && <label className="col-span-2 flex items-center gap-2 text-[10px] text-muted-foreground">Day of month<input type="number" min="1" max="31" value={dayOfMonth} onChange={(event) => setDayOfMonth(Math.min(31, Math.max(1, Number(event.target.value) || 1)))} className="ml-auto w-20 rounded-lg border border-white/8 bg-secondary/40 px-2.5 py-2 text-xs text-foreground" /></label>}
                      </div>
                    )}
                    {triggerType === "manual" && !existingProcess && <button type="button" onClick={() => setStartNow((value) => !value)} className="mt-2 flex w-full items-center gap-2.5 rounded-lg border border-white/8 bg-white/[0.02] p-2.5 text-left"><span className={`flex h-4 w-4 items-center justify-center rounded border ${startNow ? "border-primary bg-primary" : "border-white/15"}`}>{startNow && <Check className="h-3 w-3 text-primary-foreground" />}</span><span className="text-xs">Start the first case immediately</span></button>}
                  </section>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <section>
                      <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground/60"><ShieldCheck className="h-3 w-3" /> Approval boundary</p>
                      <div className="mt-2 space-y-1.5">{APPROVAL_LEVELS.map((option) => { const Icon = option.icon; const active = approval === option.value; return <button type="button" key={option.value} onClick={() => setApproval(option.value)} className={`flex w-full items-center gap-2.5 rounded-lg border p-2.5 text-left ${active ? "border-primary/40 bg-primary/10" : "border-white/8 bg-card/30 hover:bg-card/50"}`}><Icon className={`h-3.5 w-3.5 shrink-0 ${active ? "text-primary" : "text-muted-foreground"}`} /><span className="min-w-0 flex-1"><span className={`block text-xs ${active ? "font-medium text-primary" : ""}`}>{option.label}</span><span className="mt-0.5 block text-[10px] leading-snug text-muted-foreground/60">{option.detail}</span></span></button>; })}</div>
                    </section>
                    <section>
                      <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground/60"><BellRing className="h-3 w-3" /> If a workflow fails</p>
                      <div className="mt-2 space-y-1.5">{FAILURE_OPTIONS.map((option) => { const Icon = option.icon; const active = failurePolicy === option.value; return <button type="button" key={option.value} onClick={() => setFailurePolicy(option.value)} className={`flex w-full items-center gap-2.5 rounded-lg border p-2.5 text-left ${active ? "border-primary/40 bg-primary/10" : "border-white/8 bg-card/30 hover:bg-card/50"}`}><Icon className={`h-3.5 w-3.5 shrink-0 ${active ? "text-primary" : "text-muted-foreground"}`} /><span className="min-w-0 flex-1"><span className={`block text-xs ${active ? "font-medium text-primary" : ""}`}>{option.label}</span><span className="mt-0.5 block text-[10px] leading-snug text-muted-foreground/60">{option.detail}</span></span></button>; })}</div>
                    </section>
                  </div>

                  <div className="rounded-xl border border-primary/15 bg-primary/5 p-3 text-[11px] leading-relaxed text-muted-foreground">The process decides <span className="text-foreground">when</span> to continue. Each workflow still decides <span className="text-foreground">how</span>, and AURA’s safety layer decides <span className="text-foreground">what is allowed</span>.</div>
                  {error && <p role="alert" className="text-xs leading-relaxed text-red-300">{error}</p>}
                  <div className="flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded-lg border border-white/10 px-3 py-2 text-xs text-muted-foreground hover:bg-white/5">Cancel</button><button type="button" onClick={handleCreate} disabled={saving || loadingRuns || selectionLoadFailed || stages.length < 2} className="inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-primary to-accent px-4 py-2 text-xs font-medium text-white disabled:opacity-50">{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <GitBranch className="h-3.5 w-3.5" />} {existingProcess ? "Save changes" : "Create process"}</button></div>
                </div>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
