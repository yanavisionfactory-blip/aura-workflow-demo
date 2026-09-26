/** Keep the reviewed plan's identity, order, and wording during execution. */
export function alignExecutionSteps(reviewedSteps = [], runtimeSteps = []) {
  const byKey = new Map(runtimeSteps.map((step) => [step.key, step]));
  return reviewedSteps.map((planned, index) => ({
    planned,
    runtime: byKey.get(planned.key)
      || (!planned.key ? runtimeSteps[index] : undefined),
  }));
}
