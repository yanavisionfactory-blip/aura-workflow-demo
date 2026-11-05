import { useEffect, useRef, useState } from "react";
import { Check, Eye, Pencil } from "lucide-react";
import { toolResultEntries, toolResultName } from "@/lib/toolResultViews.mjs";
import { ToolOutputCards } from "./ToolResultView";

function CheckpointReview({ steps, review, busy = false, error = "", onApprove, backendRunId }) {
  const [edits, setEdits] = useState({});
  const heading = useRef(null);
  useEffect(() => { heading.current?.focus(); }, []);
  const entries = toolResultEntries(steps).filter((entry) => review.step_ids?.includes(entry.id));
  const tool = toolResultName(review.tool_slug, review.operation);
  const ready = review.step_ids?.length > 0 && entries.length === review.step_ids.length
    && entries.every((entry) => entry.status === "completed" && entry.hasResponse);
  const hasEdits = Object.keys(edits).length > 0;
  const invalidEdit = Object.values(edits).some((text) => !text.trim() || text.length > 200000);
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

    <ToolOutputCards entries={entries.filter((entry) => !Object.hasOwn(edits, entry.id))}
      activity={steps} backendRunId={backendRunId} />
    {entries.map((entry) => {
      const result = entry.preview;
      if (result?.kind !== "ai_response" || !("preview" in result)
          || typeof result.preview?.body !== "string"
          || !["anthropic.chat", "intelligence.claude_backup"].includes(entry.operation)) return null;
      return <div key={entry.id} className="space-y-3">
        {Object.hasOwn(edits, entry.id) ? <>
          <label className="block text-sm font-medium" htmlFor={`result-edit-${entry.id}`}>Edit {entry.tool} result</label>
          <textarea id={`result-edit-${entry.id}`} value={edits[entry.id]} disabled={busy} maxLength={200000} rows={18}
            onChange={(event) => setEdits({ ...edits, [entry.id]: event.target.value })}
            className="w-full rounded-xl border border-primary/40 bg-background p-4 text-sm leading-7" />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">Approval saves your edited text for the following steps. The original response stays saved.</p>
            <button type="button" disabled={busy} onClick={() => discard(entry.id)} className="text-xs underline">Discard edits</button>
          </div>
        </> : <button type="button" disabled={busy} onClick={() => setEdits({ ...edits, [entry.id]: result.preview.body })}
          className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-4 py-2.5 text-xs hover:border-primary/50">
          <Pencil className="h-4 w-4" />Edit {entry.tool} result
        </button>}
      </div>;
    })}

    {!ready && <p role="status" className="text-sm text-muted-foreground">The saved result is not ready for review yet.</p>}
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    <footer className="flex flex-wrap items-center justify-between gap-4 border-t border-white/10 pt-5">
      <p className="text-xs text-muted-foreground">Your place is saved. Nothing continues until you approve.</p>
      <button type="button" disabled={busy || !ready || invalidEdit || !onApprove}
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
