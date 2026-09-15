const FAILED_STATUSES = new Set(["blocked", "cancelled", "failed"]);

export const WORKFLOW_HISTORY_CHANGED_EVENT = "aura:workflow-history-changed";

export function announceWorkflowHistoryChanged(detail = {}) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(WORKFLOW_HISTORY_CHANGED_EVENT, { detail }));
}

export function upsertHistoryRecord(records = [], record = null) {
  if (!record?.id) return records;
  const existingIndex = records.findIndex((item) => item.id === record.id);
  if (existingIndex < 0) return [record, ...records];
  return records.map((item, index) => index === existingIndex ? record : item);
}

const displayToolName = (slug = "") => {
  const names = {
    aura: "AURA Intelligence",
    google: "Google",
    canva: "Canva",
    gmail: "Gmail",
    notion: "Notion",
    jira: "Jira",
    slack: "Slack",
    hubspot: "HubSpot",
    airtable: "Airtable",
  };
  return names[slug] || String(slug || "AURA").replace(/[-_]+/g, " ");
};

const sentence = (value, fallback) => {
  const text = String(value || fallback || "Complete this step").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Complete this step";
};

const durationSeconds = (run) => {
  const started = Date.parse(run?.created_at || "");
  const finished = Date.parse(run?.updated_at || "");
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished < started) return null;
  return (finished - started) / 1000;
};

export function isExecutedBackendRun(run = {}) {
  const scheduled = Boolean(run.execution_context?.schedule?.id);
  return Boolean(run.id && (
    (run.plan_approved && Array.isArray(run.plan?.steps))
    || scheduled
  ));
}

export function historyStatusForBackendRun(run = {}) {
  if (run.status === "completed") return "completed";
  const scheduledAttention = Boolean(run.execution_context?.schedule?.id)
    && ["awaiting_approval", "waiting_for_action"].includes(run.status);
  if (FAILED_STATUSES.has(run.status) || scheduledAttention) return "failed";
  return "running";
}

export function historyStepsForBackendRun(run = {}) {
  return (run.plan?.steps || []).map((step) => ({
    tool: displayToolName(step.tool_slug || step.tool),
    action: sentence(step.reason || step.action || step.operation),
    title: sentence(step.reason || step.action || step.operation),
    riskLevel: step.consequential ? "modify" : "read",
    output: step.expected_output || "Completed step",
  }));
}

export function backendRunHistoryProjection(run = {}) {
  const status = historyStatusForBackendRun(run);
  const title = run.plan?.name || "Saved workflow";
  const prompt = run.prompt || run.plan?.interpretation || title;
  const interpretation = run.plan?.interpretation || prompt;
  const summary = run.result?.unified_deliverable?.summary
    || run.result?.summary
    || (status === "failed" ? run.error : "")
    || (status === "running" ? "AURA is running this workflow." : "AURA completed this workflow.");
  const completedCount = Number(run.result?.completed_steps || 0);
  const steps = historyStepsForBackendRun(run);
  const runDate = run.updated_at || run.created_at || new Date().toISOString();

  return {
    workflow: {
      name: title,
      prompt,
      interpretation,
      steps,
      last_run_status: status,
      last_run_date: runDate,
      last_summary: summary,
    },
    run: {
      backend_run_id: run.id,
      prompt,
      status,
      title,
      summary,
      metrics: completedCount > 0
        ? [{ value: String(completedCount), label: completedCount === 1 ? "step completed" : "steps completed" }]
        : [],
      outcomes: [],
      steps,
      duration_seconds: durationSeconds(run),
      backend_created_at: run.created_at || runDate,
      backend_updated_at: run.updated_at || runDate,
    },
  };
}

export function backendRunNeedsSync(savedRun = null, projectedRun = {}) {
  if (!savedRun) return true;
  return savedRun.backend_updated_at !== projectedRun.backend_updated_at
    || savedRun.status !== projectedRun.status
    || savedRun.title !== projectedRun.title
    || savedRun.summary !== projectedRun.summary;
}

export function workflowForBackendRun(run = {}, workflows = []) {
  const explicitId = run.inputs?.saved_workflow_id
    || run.execution_context?.schedule?.history_workflow_id;
  if (explicitId) {
    const explicit = workflows.find((workflow) => workflow.id === explicitId);
    if (explicit) return explicit;
  }
  const prompts = new Set([
    String(run.prompt || "").trim(),
    String(run.plan?.interpretation || "").trim(),
  ].filter(Boolean));
  return workflows.find((workflow) => prompts.has(String(workflow.prompt || "").trim())) || null;
}

export function workflowRollup(workflowId, runs = []) {
  const workflowRuns = runs
    .filter((run) => run.workflow_id === workflowId)
    .sort((left, right) => Date.parse(right.backend_updated_at || right.updated_date || right.created_date || 0)
      - Date.parse(left.backend_updated_at || left.updated_date || left.created_date || 0));
  const latest = workflowRuns[0];
  if (!latest) return { run_count: 0 };
  return {
    run_count: workflowRuns.length,
    last_run_status: latest.status,
    last_run_date: latest.backend_updated_at || latest.updated_date || latest.created_date,
    last_summary: latest.summary,
    steps: latest.steps || [],
  };
}
