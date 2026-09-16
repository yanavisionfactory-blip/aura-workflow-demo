export const PROCESS_CHANGED_EVENT = "aura:process-changed";

export function announceProcessChanged(detail = {}) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(PROCESS_CHANGED_EVENT, { detail }));
}

export function processTriggerLabel(process) {
  const trigger = process?.trigger || {};
  if (trigger.type === "event") return `When ${trigger.event_type}`;
  if (trigger.type !== "schedule") return "Started manually";
  const at = trigger.local_time || "08:00";
  if (trigger.cadence === "daily") return `Daily at ${at}`;
  if (trigger.cadence === "weekly") return `Weekly at ${at}`;
  if (trigger.cadence === "monthly") return `Monthly at ${at}`;
  return "Scheduled";
}

export function processStatusLabel(status) {
  return {
    pending: "Ready",
    waiting: "Waiting for time",
    waiting_event: "Waiting for event",
    running: "Running",
    paused: "Paused",
    attention: "Needs attention",
    completed: "Completed",
    stopped: "Stopped",
  }[status] || status || "Unknown";
}

export function processStatusTone(status) {
  if (status === "completed") return "text-emerald-400 bg-emerald-400/10 border-emerald-400/20";
  if (status === "attention") return "text-amber-300 bg-amber-400/10 border-amber-400/20";
  if (status === "running") return "text-primary bg-primary/10 border-primary/20";
  return "text-muted-foreground bg-white/[0.03] border-white/[0.08]";
}
