import { useEffect, useRef, useState } from "react";
import { Check, Eye } from "lucide-react";
import { toolResultEntries, toolResultName } from "@/lib/toolResultViews.mjs";
import { ToolOutputCards } from "./ToolResultView";
import GeneratedResultEditor from "./GeneratedResultEditor";
import { editableResultText, MAX_RESULT_TEXT } from "@/lib/toolOutputEditing.mjs";

function CheckpointReview({ steps, review, busy = false, error = "", onApprove, backendRunId }) {
  const [edits, setEdits] = useState({});
  const [editingWithAI, setEditingWithAI] = useState({});
  const heading = useRef(null);
  useEffect(() => { heading.current?.focus(); }, []);
  const entries = toolResultEntries(steps).filter((entry) => review.step_ids?.includes(entry.id));
  const tool = toolResultName(review.tool_slug, review.operation);
  const ready = review.step_ids?.length > 0 && entries.length === review.step_ids.length
    && entries.every((entry) => entry.status === "completed" && entry.hasResponse);
  const hasEdits = Object.keys(edits).length > 0;
  const invalidEdit = Object.values(edits).some((text) => !text.trim() || text.length > MAX_RESULT_TEXT);
  const locked = busy || Object.values(editingWithAI).some(Boolean);
  const sourceSteps = new Map(steps.map((step) => [step.id || step.stepKey || step.key, step]));
  const editable = entries.filter((entry) => editableResultText(sourceSteps.get(entry.id)) !== null);
  const editableIds = new Set(editable.map((entry) => entry.id));
  const previewSteps = steps.map((step) => Object.hasOwn(edits, step.id || step.stepKey || step.key)
    ? { ...step, output: { ...step.output, user_revision: { text: edits[step.id || step.stepKey || step.key] } } } : step);
  const previewEntries = toolResultEntries(previewSteps);
  const discard = (id) => setEdits((current) => {
    const next = { ...current };
    delete next[id];
    return next;
  });

  return <section aria-label="Tool result review" className="mx-auto w-full max-w-6xl space-y-6">
    <header className="flex items-start gap-3">
      <div className="rounded-xl border border-primary/20 bg-primary/10 p-3"><Eye className="h-5 w-5 text-primary" /></div>
      <div>
        <h2 ref={heading} tabIndex={-1} className="text-xl font-semibold outline-none">Review {tool} result</h2>
        <p className="mt-2 text-sm text-muted-foreground">{review.is_final
          ? "The final tool has finished. Review the result, make any edits, then approve to finish."
          : "This tool has finished. Review the result, make any edits, then approve. Execution resumes automatically."}</p>
      </div>
    </header>

    <ToolOutputCards entries={entries.filter((entry) => !editableIds.has(entry.id))}
      activity={steps} backendRunId={backendRunId} />
    {editable.map((entry) => {
      const source = sourceSteps.get(entry.id);
      const original = typeof source.output?.user_revision?.text === "string"
        ? source.output.user_revision.text : editableResultText(source);
      const value = Object.hasOwn(edits, entry.id) ? edits[entry.id] : original;
      return <GeneratedResultEditor key={entry.id} tool={entry.tool} value={value}
        changed={Object.hasOwn(edits, entry.id)} disabled={locked}
        onChange={(text) => text === original ? discard(entry.id) : setEdits((current) => ({ ...current, [entry.id]: text }))}
        onDiscard={() => discard(entry.id)}
        onBusyChange={(working) => setEditingWithAI((current) => ({ ...current, [entry.id]: working }))}>
        <ToolOutputCards entries={previewEntries.filter((item) => item.id === entry.id)}
          activity={previewSteps} backendRunId={backendRunId} />
      </GeneratedResultEditor>;
    })}

    {!ready && <p role="status" className="text-sm text-muted-foreground">The saved result is not ready for review yet.</p>}
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    <footer className="flex flex-wrap items-center justify-between gap-4 border-t border-white/10 pt-5">
      <p className="text-xs text-muted-foreground">Your place is saved. Nothing continues until you approve.</p>
      <button type="button" disabled={locked || !ready || invalidEdit || !onApprove}
        onClick={() => onApprove(hasEdits ? edits : null)}
        className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white hover:bg-primary/90 disabled:opacity-50">
        <Check className="h-4 w-4" />{busy ? "Approving…" : review.is_final ? "Approve and finish" : "Approve result"}
      </button>
    </footer>
  </section>;
}

export default function ToolOutputReview(props) {
  // A new checkpoint starts a fresh editor; updates to the same checkpoint
  // preserve unsaved edits, including after an unsuccessful approval request.
  return <CheckpointReview key={props.review.step_id} {...props} />;
}
