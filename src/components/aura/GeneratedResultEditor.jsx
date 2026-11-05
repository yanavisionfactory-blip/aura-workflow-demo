import { useEffect, useId, useRef, useState } from "react";
import { Pencil, Sparkles, Undo2 } from "lucide-react";
import { aura } from "@/api/auraClient";
import { MAX_RESULT_TEXT, resultTextEditPrompt, resultTextEditSchema, validateResultTextEdit } from "@/lib/toolOutputEditing.mjs";

export default function GeneratedResultEditor({ tool, value, changed, disabled = false, onChange, onDiscard, onBusyChange, children }) {
  const [mode, setMode] = useState("view");
  const [instruction, setInstruction] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [undo, setUndo] = useState(null);
  const request = useRef(0);
  const pending = useRef(false);
  const active = useRef(true);
  const id = useId();
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);

  const cancelAI = () => {
    request.current += 1;
    pending.current = false;
    setWorking(false); onBusyChange(false); setMode("view"); setError("");
  };
  const revise = async () => {
    if (pending.current || disabled || !instruction.trim()) return;
    const generation = ++request.current;
    pending.current = true;
    setWorking(true); onBusyChange(true); setError(""); setMessage("");
    try {
      const prompt = resultTextEditPrompt(value, instruction);
      const suggestion = validateResultTextEdit(await aura.integrations.Core.InvokeLLM({ prompt, response_json_schema: resultTextEditSchema }));
      if (!active.current || generation !== request.current) return;
      setUndo(value); onChange(suggestion.text);
      setMessage(suggestion.summary || "Preview updated. Review the changes before approving.");
      setInstruction(""); setMode("view");
    } catch (failure) {
      if (active.current && generation === request.current) setError(failure?.message || "AI couldn't update this result. Your edits are still here.");
    } finally {
      if (active.current && generation === request.current) {
        pending.current = false; setWorking(false); onBusyChange(false);
      }
    }
  };
  const locked = disabled || working;
  return <section aria-label={`${tool} result editor`} className="space-y-4">
    <div className="flex flex-wrap items-center gap-3">
      <button type="button" disabled={locked} aria-pressed={mode === "manual"}
        onClick={() => { setMode(mode === "manual" ? "view" : "manual"); setError(""); }}
        className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-4 py-2.5 text-sm disabled:opacity-50">
        <Pencil className="h-4 w-4" />{mode === "manual" ? "Done editing" : "Edit manually"}
      </button>
      <button type="button" disabled={locked} aria-pressed={mode === "ai"}
        onClick={() => { setMode(mode === "ai" ? "view" : "ai"); setError(""); }}
        className="inline-flex items-center gap-2 rounded-xl border border-primary/30 bg-primary/10 px-4 py-2.5 text-sm text-primary disabled:opacity-50">
        <Sparkles className="h-4 w-4" />Edit with AI
      </button>
      {changed && <span className="text-xs text-amber-200">Unsaved changes</span>}
    </div>
    {mode === "ai" && <form onSubmit={(event) => { event.preventDefault(); void revise(); }} className="space-y-3 rounded-xl border border-primary/25 bg-primary/5 p-4">
      <label htmlFor={`${id}-prompt`} className="block text-sm font-medium">What should AI change?</label>
      <textarea id={`${id}-prompt`} value={instruction} disabled={locked} maxLength={6000} rows={3}
        onChange={(event) => setInstruction(event.target.value)} placeholder="For example: Add a conversions section and make the wording more concise."
        className="w-full rounded-lg border border-white/15 bg-background p-3 text-sm leading-6" />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">AI updates this preview. Review the changes before approving.</p>
        <div className="flex gap-3"><button type="button" disabled={disabled && !working} onClick={cancelAI} className="text-xs underline">Cancel AI edit</button>
          <button type="submit" disabled={locked || !instruction.trim()} className="rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50">{working ? "Updating preview…" : "Apply AI edit"}</button></div>
      </div>
    </form>}
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    {message && <div role="status" className="flex flex-wrap items-center gap-3 text-sm text-emerald-300">
      <span>{message}</span>{undo !== null && <button type="button" disabled={locked} onClick={() => {
        onChange(undo); setUndo(null); setMessage("AI edit undone. Your previous version is restored.");
      }} className="inline-flex items-center gap-1 text-xs underline"><Undo2 className="h-3.5 w-3.5" />Undo AI edit</button>}
    </div>}
    {mode === "manual" ? <div className="space-y-3">
      <label htmlFor={`${id}-text`} className="block text-sm font-medium">Edit {tool} result</label>
      <textarea id={`${id}-text`} value={value} disabled={locked} maxLength={MAX_RESULT_TEXT} rows={18}
        onChange={(event) => { onChange(event.target.value); setUndo(null); setMessage(""); }}
        className="w-full rounded-xl border border-primary/40 bg-background p-4 text-sm leading-7" />
    </div> : children}
    {changed && <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-xs text-muted-foreground">Approval saves this version for the following steps. The original response stays saved.</p>
      <button type="button" disabled={locked} onClick={() => { onDiscard(); setMode("view"); setUndo(null); setMessage(""); setError(""); }} className="text-xs underline">Discard edits</button>
    </div>}
  </section>;
}
