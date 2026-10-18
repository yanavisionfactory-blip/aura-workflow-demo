import { primaryResultFromOutputs, readableResultText } from "./resultPresentation.mjs";
import { normalizeResultSuggestions } from "./resultSuggestions.mjs";

// Reconstruct the result from saved receipts only. Opening history must never
// dispatch, resume, synthesize, or repeat a provider action.
export function savedRunResults(run = {}) {
  const complete = run.status === "completed";
  const steps = run.steps || [];
  const keys = new Map(steps.map((step) => [step.id, step.key]));
  const recorded = run.result?.outputs?.length ? run.result.outputs : steps
    .filter((step) => step.status === "completed" && step.output?.provider_result)
    .map((step) => ({ ...step.output, step_id: step.id, operation: step.output.operation || step.operation }));
  const outputs = recorded.map((output) => ({ ...output, step_key: output.step_key || keys.get(output.step_id) }));
  const synthesis = run.result?.unified_deliverable || {};
  const title = run.plan?.name || "Saved workflow results";
  const summary = complete
    ? readableResultText(synthesis.summary || run.result?.summary, "The saved workflow result is ready to review.")
    : "This workflow has not completed. Completed app results are shown below; remaining steps still need attention.";
  const detail = readableResultText(synthesis.deliverable, summary);
  const resultPresentation = complete ? run.result?.result_presentation || null : null;
  const primaryResult = primaryResultFromOutputs(outputs, { title, summary, deliverable: detail }, resultPresentation);
  return {
    status: complete ? "completed" : "needs_attention",
    title: complete ? primaryResult.completionTitle || title : `${title} — incomplete`,
    summary: complete ? primaryResult.completionSummary || summary : summary,
    primaryResult,
    resultPresentation,
    metrics: complete ? resultPresentation?.metrics || [] : [],
    outcomes: [{ type: "document", title: "Saved result", detail, link: primaryResult.link, linkLabel: primaryResult.linkLabel }],
    nextSteps: complete ? normalizeResultSuggestions(synthesis.next_steps) : [],
    suggestionsLoading: false,
  };
}
