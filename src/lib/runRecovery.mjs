// Presentation only. The resume endpoint remains the authority for recovery.
export const needsRecovery = (status) => ["waiting_for_action", "blocked", "failed"].includes(status);

const AUTO_MONITOR_STATUSES = new Set(["queued", "planning", "running"]);
const ATTENTION_STATUSES = new Set(["awaiting_approval", "waiting_for_action", "blocked", "failed"]);

// Restoring a durable run must not turn the AURA home screen into a dead end.
// Active work keeps running and is observed automatically; anything that needs
// a person is presented as an optional attention card on the home screen.
export function startupRunDisposition(run = {}) {
  if (AUTO_MONITOR_STATUSES.has(run.status)) return "monitor";
  if (ATTENTION_STATUSES.has(run.status)) return "attention";
  return "ignore";
}

export function alternativeRecoveryPrompt(run = {}, userApproach = "") {
  const original = String(run.prompt || "Continue the saved workflow").trim();
  const approach = String(userApproach || "").trim();
  const recovery = recoveryForRun(run);
  const direction = approach
    ? `Use this approach from the user: ${approach}`
    : "Propose a different policy-safe approach that avoids this blocker.";
  return `${original}\n\nRecovery request: ${direction} The previous run is paused at: ${recovery.what} Preserve completed work, do not repeat any external action whose outcome is uncertain, and ask for approval before every new consequential action.`;
}

export function recoveryForRun(run = {}) {
  const steps = run.steps || [];
  const blocker = run.blocker;
  if (blocker) {
    let blockerIndex = steps.findIndex((step) => step.id === blocker.step_id);
    if (blockerIndex < 0) {
      blockerIndex = steps.findIndex((step) => !["completed", "skipped"].includes(step.status));
    }
    const connectionAction = ["connect_account", "reconnect_account"].includes(blocker.action);
    const labels = {
      plan_approval_required: "The workflow plan needs your approval.",
      external_submission_approval_required: "An external submission needs your approval.",
      oauth_required: "The selected app account needs to be reconnected.",
      connection_required: "This workflow needs an app connection.",
      connection_unverified: "AURA could not verify the selected app account.",
      permission_required: "The selected account is missing required permission.",
      resource_ambiguous: "AURA found more than one possible resource.",
      resource_not_found: "AURA could not find the required resource.",
      resource_access_denied: "The connected account cannot access the required resource.",
      external_effect_uncertain: "AURA cannot safely repeat an external action.",
    };
    const fixes = {
      connect_account: "Connect the requested account once; AURA will preserve this run and continue from the same point.",
      reconnect_account: "Restore access to the selected account once; AURA will re-run preflight and continue from the same point.",
      choose_resource: "Choose the exact account or resource AURA should use. The saved run will then continue without repeating completed work.",
      review_plan: "Review the plan and start it when it is correct.",
      review_submission: "Review the exact prepared payload. AURA will submit it only after you approve it.",
      inspect_run: "Review the provider result before deciding what should happen next; completed work and receipts are preserved.",
    };
    return {
      index: blockerIndex >= 0 ? blockerIndex : null,
      stepId: blocker.step_id || null,
      blockerCode: blocker.code,
      blockerAction: blocker.action,
      toolSlug: blocker.tool_slug || null,
      connectionId: blocker.connection_id || null,
      resourceName: blocker.resource_name || null,
      connectedAccount: blocker.connected_account || null,
      what: labels[blocker.code] || "AURA stopped at a required human decision.",
      why: blocker.message || "AURA cannot safely continue this run without this decision.",
      fix: fixes[blocker.action] || "Resolve the exact blocker shown above, then return to this saved run.",
      canRetry: connectionAction,
      canSkip: false,
      buttonLabel: blocker.action === "reconnect_account" ? "Reconnect account" : "Connect account",
      subtitle: "This is a required human action. Everything else remains saved and unattended.",
    };
  }
  let index = steps.findIndex((s) => s.status === "failed");
  if (index < 0) index = steps.findIndex((s) => !["completed", "skipped"].includes(s.status));
  const step = steps[index];
  const text = `${step?.error || ""} ${run.error || ""}`.toLowerCase();
  const recoverable = ["waiting_for_action", "failed"].includes(run.status);
  const attempts = run.execution_context?.__aura_recovery__?.[step?.id] || 0;
  const reviewOnly = !step && steps.length > 0 && Boolean(run.result?.verification)
    && steps.every((s) => ["completed", "skipped"].includes(s.status));
  let retry = recoverable && attempts < 3 &&
    ((step?.status === "failed" && (step.consequential === false || step.recovery?.can_retry === true)) || reviewOnly);
  const optional = run.plan?.steps?.[step?.position ?? index]?.optional === true;
  const skip = recoverable && attempts < 3 && step?.status === "failed" && optional;
  const connectionBlocked = /authorization_required|connection needs your attention|reconnect|authorization|access.*expired/.test(text);
  const googleResourceBlocked = connectionBlocked &&
    (step?.tool_slug === "google" || /google|spreadsheet|sheet/.test(`${step?.operation || ""} ${text}`));
  let what = "AURA couldn't finish this step.";
  let why = "The available information doesn't identify a specific cause yet.";
  let fix = retry
    ? "Try this step again. AURA will keep the work already completed."
    : "Check the current status. AURA has kept the work already completed.";
  if (/configuration|administrator|client.id/.test(text)) {
    retry = false;
    what = "This app's connection setup needs correcting.";
    why = "The problem is with the app's setup. Signing in again won't fix it.";
    fix = "An administrator needs to check the app configuration before you continue.";
  } else if (googleResourceBlocked) {
    what = "AURA can't access a required Google Drive resource.";
    why = "The connected Google account cannot open the original spreadsheet needed for this workflow.";
    fix = "Open Connections, manage Google Drive, and reconnect with the account that can open both original sheets. Then return here and retry this step.";
  } else if (connectionBlocked || /connection/.test(text)) {
    what = "An app connection needs attention.";
    why = "AURA couldn't use the access needed for this step.";
    fix = "Open Connections at the top of the page and check this app's access, then return here.";
  } else if (/may already|uncertain|duplicate|reconcile/.test(text)) {
    retry = false;
    what = "AURA couldn't confirm whether this action finished.";
    why = "Repeating it could create a duplicate.";
    fix = "Check the result in the connected app. This action needs its outcome verified before it can continue.";
  } else if (/rate.limit|too many requests/.test(text)) {
    what = "The app is asking AURA to slow down.";
    why = "The app's request limit was reached.";
    fix = "Give the app a little time before trying this step again.";
  } else if (/timeout|timed out|temporarily unavailable/.test(text)) {
    what = "AURA couldn't get a response in time.";
    why = "The app or connection may be temporarily unavailable.";
  } else if (/not found|couldn't find|could not find/.test(text)) {
    what = "AURA couldn't find something needed for this step.";
    why = "The requested item may be missing or unavailable to the connected account.";
    fix = "Check that the item exists and is shared with the connected account, then try again.";
  }
  if (step?.status === "failed" && step.recovery?.phase === "before_action" && !/connection|configuration/.test(text)) {
    what = "AURA stopped before sending this action to the app.";
    why = /processing limit/.test(text)
      ? "The source content could not be fully prepared within this run's processing limit."
      : "AURA couldn't finish preparing this step.";
    fix = retry
      ? "Retry this step. AURA will reuse the completed work and prepare the action for your review."
      : "Your completed work is saved. This preparation problem needs resolving before you continue.";
  } else if (step?.consequential && step.status === "failed" && !/connection|configuration/.test(text)) {
    fix = "Check the result in the connected app. AURA won't automatically repeat an action that could already have happened.";
  }
  if (attempts >= 3) fix = "This step has reached its retry limit. The underlying problem needs checking before another attempt.";
  return { index: index >= 0 ? index : null, stepId: step?.id || null,
    what, why, fix, canRetry: retry, canSkip: skip,
    buttonLabel: retry
      ? (reviewOnly ? "Check the final result again" : connectionBlocked ? "Retry after reconnecting" : "Retry this step")
      : "Check status",
    subtitle: needsRecovery(run.status) ? "Your completed work is saved. Choose the next step below."
      : "AURA couldn't refresh the workflow status. Check before starting anything again.",
  };
}
