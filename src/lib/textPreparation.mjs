// Only the server can certify a pinned text-only action as preparation. A tool
// name, prompt field, or planner risk label is never permission to run a write.
export function pendingTextPreparation(run = {}) {
  if (!run.plan_approved || run.status !== "awaiting_approval"
    || run.tool_output_review?.step_id) return null;
  const ready = (run.steps || []).filter((step) => step.status === "awaiting_approval"
    && step.approval_status === "pending" && step.approval_preview?.status === "ready");
  // Do not advance text preparation past an external action awaiting review.
  const step = ready[0];
  return step?.preparation_only === true && step.approval_id
    && !Object.hasOwn(step.output || {}, "provider_result") ? step : null;
}

export async function continueTextPreparation(run, decideApproval, attempted) {
  const step = pendingTextPreparation(run);
  if (!step || attempted.has(step.approval_id)) return false;
  attempted.add(step.approval_id);
  try {
    // Preserve the saved arguments and immutable plan. Start already authorized
    // this request; the next visible review is its actual saved response.
    await decideApproval(step.approval_id, true);
  } catch (error) {
    // Another tab may have advanced this approval. Re-read once; never replay it.
    if (error?.status !== 409) throw error;
  }
  return true;
}
