import { useEffect, useState } from "react";
import { ArrowRight, Eye, Pencil } from "lucide-react";
import { toolResultEntries, toolResultName } from "@/lib/toolResultViews.mjs";
import ToolResultDialog from "./ToolResultView";

function OutputPreviews({ entries, onOpen }) {
  return <div className="flex flex-wrap gap-2">{entries.filter((entry) => entry.hasResponse).map((entry) =>
    <button key={entry.id} type="button" onClick={() => onOpen(entry.id)} className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-4 py-2.5 text-xs hover:border-primary/50">
      <Eye className="h-4 w-4" />Preview {entry.tool}{entry.action ? ` · ${entry.action}` : ""}
    </button>
  )}</div>;
}

// Mounted by the live workflow only; offline demo playback has no account client.
export default function ExecutionToolOutputs({ steps, review, reviewBusy = false, reviewError = "", onContinue, backendRunId }) {
  const [toolView, setToolView] = useState(null);
  const [edits, setEdits] = useState({});
  useEffect(() => { setEdits({}); }, [review?.step_id]);
  const entries = toolResultEntries(steps);
  const currentOutputs = review ? entries.filter((entry) => review.step_ids?.includes(entry.id)) : [];
  const earlierOutputs = entries.filter((entry) => !review?.step_ids?.includes(entry.id));
  const nextTool = review?.next_tool_slug ? toolResultName(review.next_tool_slug, review.next_operation) : null;
  const hasEdits = Object.keys(edits).length > 0;
  const invalidEdit = Object.values(edits).some((text) => !text.trim() || text.length > 200000);
  return <>
      {review && <section aria-label="Tool output checkpoint" className="mb-6 space-y-4">
        <p className="text-sm text-muted-foreground">This tool has finished. Review the result and edit it if needed, then {review.is_final ? "open your results" : "continue to the next tool"}.</p>
        <OutputPreviews entries={currentOutputs} onOpen={(id) => setToolView({ id })} />
        {currentOutputs.map((entry) => entry.preview?.kind === "ai_response" ? <div key={entry.id} className="space-y-3">
          {Object.hasOwn(edits, entry.id) ? <>
            <label className="block text-sm font-medium" htmlFor={`result-edit-${entry.id}`}>Edit {entry.tool} result</label>
            <textarea id={`result-edit-${entry.id}`} value={edits[entry.id]} disabled={reviewBusy} maxLength={200000} rows={12}
              onChange={(event) => setEdits({ ...edits, [entry.id]: event.target.value })}
              className="w-full rounded-xl border border-primary/40 bg-background p-4 text-sm leading-6" />
            <div className="flex items-center justify-between gap-3"><p className="text-xs text-muted-foreground">Your edited text will be used by the next steps. The original response stays saved.</p>
              <button type="button" disabled={reviewBusy} onClick={() => setEdits((current) => { const next = { ...current }; delete next[entry.id]; return next; })} className="shrink-0 text-xs underline">Discard edits</button></div>
          </> : <button type="button" disabled={reviewBusy} onClick={() => setEdits({ ...edits, [entry.id]: entry.preview.preview.body })} className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-4 py-2.5 text-xs hover:border-primary/50"><Pencil className="h-4 w-4" />Edit {entry.tool} result</button>}
        </div> : null)}
        {currentOutputs.filter((entry) => entry.preview?.kind === "spreadsheet" && entry.link).map((entry) =>
          <a key={entry.id} href={entry.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-4 py-2.5 text-xs hover:border-primary/50"><Pencil className="h-4 w-4" />Edit in Google Sheets</a>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/20 bg-primary/5 p-4">
          <p className="text-xs text-muted-foreground">{review.is_final ? "All tool outputs are saved." : "The next tool is paused until you continue."}</p>
          <button type="button" disabled={reviewBusy || !onContinue || invalidEdit} onClick={() => onContinue(hasEdits ? edits : null)} className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white hover:bg-primary/90 disabled:opacity-50">
            {reviewBusy ? "Continuing…" : hasEdits ? "Save edits and continue" : review.is_final ? "Continue to results" : `Continue${nextTool ? ` to ${nextTool}` : " workflow"}`}<ArrowRight className="h-4 w-4" />
          </button>
        </div>
        {reviewError && <p role="alert" className="text-sm text-rose-300">{reviewError}</p>}
      </section>}
      {earlierOutputs.some((entry) => entry.status === "completed" && entry.hasResponse) && <section aria-label="Completed tool outputs" className="mb-6 space-y-3">
        <h3 className="text-sm font-semibold">{review ? "Previous tool outputs" : "Outputs from this run"}</h3>
        <OutputPreviews entries={earlierOutputs} onOpen={(id) => setToolView({ id })} />
      </section>}

    <ToolResultDialog request={toolView} onClose={() => setToolView(null)} entries={entries} primary={{}} results={{}} activity={steps} backendRunId={backendRunId} />
  </>;
}
