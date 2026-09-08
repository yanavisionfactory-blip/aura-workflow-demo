// Presentation only. The resume endpoint remains the authority for recovery.
export const needsRecovery = (status) => ["waiting_for_action", "blocked", "failed"].includes(status);

export function recoveryForRun(run = {}) {
  const steps = run.steps || [];
  let index = steps.findIndex((s) => s.status === "failed");
  if (index < 0) index = steps.findIndex((s) => !["completed", "skipped"].includes(s.status));
  const step = steps[index];
  const text = `${step?.error || ""} ${run.error || ""}`.toLowerCase();
  const recoverable = ["waiting_for_action", "failed"].includes(run.status);
  const attempts = run.execution_context?.__aura_recovery__?.[step?.id] || 0;
  const reviewOnly = !step && steps.length > 0 && Boolean(run.result?.verification)
    && steps.every((s) => ["completed", "skipped"].includes(s.status));
  let retry = recoverable && attempts < 3 &&
    ((step?.status === "failed" && step.consequential === false) || reviewOnly);
  const optional = run.plan?.steps?.[step?.position ?? index]?.optional === true;
  const skip = recoverable && attempts < 3 && step?.status === "failed" && optional;
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
  } else if (/connection|reconnect|authorization|access.*expired/.test(text)) {
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
  if (step?.consequential && step.status === "failed" && !/connection|configuration/.test(text)) {
    fix = "Check the result in the connected app. AURA won't automatically repeat an action that could already have happened.";
  }
  if (attempts >= 3) fix = "This step has reached its retry limit. The underlying problem needs checking before another attempt.";
  return { index: index >= 0 ? index : null, stepId: step?.id || null,
    what, why, fix, canRetry: retry, canSkip: skip,
    buttonLabel: retry ? (reviewOnly ? "Check the final result again" : "Retry this step") : "Check status",
    subtitle: needsRecovery(run.status) ? "Your completed work is saved. Choose the next step below."
      : "AURA couldn't refresh the workflow status. Check before starting anything again.",
  };
}
