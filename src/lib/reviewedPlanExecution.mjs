// Restoring an already started plan must not bring back the old input-preview
// gate. The server binds this transition to the existing immutable approval;
// it does not acknowledge results or reset/replay completed provider actions.
export function needsReviewedPlanResume(run = {}) {
  const context = run.execution_context || {};
  return Boolean(run.id && run.plan_approved && run.plan?.steps?.length
    && run.status === "awaiting_approval"
    && context.execution_mode !== "unattended"
    && !context.__aura_tool_output_review__?.execute_reviewed_plan);
}

export async function continueReviewedPlan(run, resume, attempted) {
  if (!needsReviewedPlanResume(run)) return false;
  if (attempted.has(run.id)) {
    throw new Error("AURA couldn't restore this saved run yet. Check its status to try again.");
  }
  attempted.add(run.id);
  await resume(run.id);
  return true; // Fetch the committed state, including any completed-result review.
}
