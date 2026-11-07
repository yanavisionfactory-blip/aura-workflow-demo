import { primaryResultFromOutputs } from "./resultPresentation.mjs";
import { operationStepTitle } from "./planPresentation.mjs";
import { toolResultName } from "./toolResultViews.mjs";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function parseRunCollection(value) {
  if (value?.kind !== "saved_run_collection" || typeof value.title !== "string" || !value.title.trim()
    || !Array.isArray(value.sources) || !value.sources.length || value.sources.length > 12) throw new Error("Choose a title and up to 12 saved runs.");
  const seen = new Set();
  const sources = value.sources.map(({ runId, stepIds }) => {
    if (!uuid.test(runId) || seen.has(runId) || !Array.isArray(stepIds) || !stepIds.length || stepIds.length > 100
      || stepIds.some((id) => !uuid.test(id)) || new Set(stepIds).size !== stepIds.length) throw new Error("Choose valid, distinct saved actions for each run.");
    seen.add(runId); return { runId, stepIds };
  });
  return { kind: "saved_run_collection", title: value.title.trim().slice(0, 180), sources };
}
export function collectionActivity(collection, runs) {
  return parseRunCollection(collection).sources.flatMap(({ runId, stepIds }) => {
    const run = runs.find((item) => item.id === runId);
    if (!run) throw new Error("A source run is unavailable in this workspace.");
    return stepIds.map((id) => {
      const step = run.steps.find((item) => item.id === id);
      if (step?.status !== "completed" || !step.output?.provider_result || step.output.provider_result.error || step.output.provider_result.isError) throw new Error("A selected action has no completed saved result. Review the source run.");
      const tool = toolResultName(step.tool_slug, step.operation);
      return { ...step, runId, originalStepKey: step.key, id: `${runId}:${step.id}`, stepKey: `${runId}:${step.key || step.id}`, tool,
        action: operationStepTitle(step, tool) || step.reason || "Saved action" };
    });
  });
}
export function collectionResults(collection, activity) {
  const outputs = activity.map((step) => ({ ...step.output, step_id: step.id, step_key: step.stepKey, operation: step.output?.operation || step.operation }));
  const summary = `Saved outputs from ${collection.sources.length} source ${collection.sources.length === 1 ? "run" : "runs"}. Each result below comes from its selected completed action. Original run history is preserved.`;
  return { collection: true, title: collection.title, summary, status: "completed", metrics: [], outcomes: [], nextSteps: [],
    primaryResult: primaryResultFromOutputs(outputs, { title: collection.title, summary }) };
}
