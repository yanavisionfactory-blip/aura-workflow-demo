export const WORKFLOW_SCHEDULE_CHANGED_EVENT = "aura:workflow-schedule-changed";

export function browserTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function schedulePayload({
  backendRunId,
  historyWorkflowId,
  title,
  cadence,
  dayOfWeek,
  dayOfMonth,
  time,
  approvalMode,
  notifyCompleted,
  notifyAttention,
  timezone = browserTimezone(),
}) {
  return {
    source_run_id: backendRunId,
    history_workflow_id: historyWorkflowId || null,
    name: title || "Scheduled workflow",
    cadence,
    timezone,
    local_time: time,
    day_of_week: cadence === "weekly" ? dayOfWeek : null,
    day_of_month: cadence === "monthly" ? dayOfMonth : null,
    approval_mode: approvalMode,
    notify_on_completion: notifyCompleted,
    notify_on_attention: notifyAttention,
  };
}

export function schedulesForWorkflow(schedules = [], workflow = {}) {
  return schedules.filter((schedule) => (
    (schedule.history_workflow_id && schedule.history_workflow_id === workflow.id)
    || (!schedule.history_workflow_id && schedule.workflow_prompt === workflow.prompt)
  ));
}

export function announceWorkflowScheduleChanged(detail = {}) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(WORKFLOW_SCHEDULE_CHANGED_EVENT, { detail }));
}

export function scheduleSummary(schedule) {
  const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  if (schedule.cadence === "daily") return `Every day at ${schedule.local_time}`;
  if (schedule.cadence === "weekly") {
    return `Every ${dayNames[schedule.day_of_week] || "week"} at ${schedule.local_time}`;
  }
  return `Day ${schedule.day_of_month} of each month at ${schedule.local_time}`;
}
