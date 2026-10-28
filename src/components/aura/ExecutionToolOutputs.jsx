import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { toolResultEntries, toolResultName } from "@/lib/toolResultViews.mjs";
import ToolResultDialog, { ToolOutputCards } from "./ToolResultView";

// Mounted by the live workflow only; offline demo playback has no account client.
export default function ExecutionToolOutputs({ steps, review, reviewBusy = false, reviewError = "", onContinue, backendRunId }) {
  const [toolView, setToolView] = useState(null);
  const entries = toolResultEntries(steps);
  const currentOutputs = review ? entries.filter((entry) => review.step_ids?.includes(entry.id)) : [];
  const earlierOutputs = entries.filter((entry) => !review?.step_ids?.includes(entry.id));
  const nextTool = review?.next_tool_slug ? toolResultName(review.next_tool_slug, review.next_operation) : null;
  return <>
      {review && <section aria-label="Tool output checkpoint" className="mb-6 space-y-4">
        <p className="text-sm text-muted-foreground">This tool has finished. Review its saved output, then {review.is_final ? "open your results" : "continue to the next tool"}.</p>
        <ToolOutputCards entries={currentOutputs} activity={steps} backendRunId={backendRunId} onOpen={(id) => setToolView({ id })} />
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/20 bg-primary/5 p-4">
          <p className="text-xs text-muted-foreground">{review.is_final ? "All tool outputs are saved." : "The next tool is paused until you continue."}</p>
          <button type="button" disabled={reviewBusy || !onContinue} onClick={onContinue} className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white hover:bg-primary/90 disabled:opacity-50">
            {reviewBusy ? "Continuing…" : review.is_final ? "Continue to results" : `Continue${nextTool ? ` to ${nextTool}` : " workflow"}`}<ArrowRight className="h-4 w-4" />
          </button>
        </div>
        {reviewError && <p role="alert" className="text-sm text-rose-300">{reviewError}</p>}
      </section>}
      {earlierOutputs.some((entry) => entry.status === "completed" && entry.hasResponse) && <section aria-label="Completed tool outputs" className="mb-6 space-y-3">
        <h3 className="text-sm font-semibold">{review ? "Previous tool outputs" : "Outputs from this run"}</h3>
        <ToolOutputCards entries={earlierOutputs} activity={steps} backendRunId={backendRunId} onOpen={(id) => setToolView({ id })} />
      </section>}

    <ToolResultDialog request={toolView} onClose={() => setToolView(null)} entries={entries} primary={{}} results={{}} activity={steps} backendRunId={backendRunId} />
  </>;
}
