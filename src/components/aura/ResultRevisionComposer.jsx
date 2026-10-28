import { useState } from "react";
import { ArrowUp, Loader2, Sparkles } from "lucide-react";

export default function ResultRevisionComposer({ onSubmit, label = "What would you like to change?", placeholder = "Describe a change to this result…", hint = "AURA keeps this result as context and prepares the next run for review." }) {
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!onSubmit) return null;
  const submit = async (event) => {
    event.preventDefault();
    if (!instruction.trim() || busy) return;
    setBusy(true); setError("");
    try { await onSubmit(instruction.trim()); setInstruction(""); }
    catch { setError("The change could not be prepared. Your text is kept; try again."); }
    finally { setBusy(false); }
  };
  return <form onSubmit={submit} aria-label="Change result with a prompt" className="mt-4 rounded-2xl border border-violet-400/25 bg-violet-400/[0.04] p-4"><label htmlFor="result-change-prompt" className="mb-3 flex items-center gap-2 text-sm font-medium"><Sparkles className="h-4 w-4 text-violet-400" />{label}</label><div className="flex items-end gap-3"><textarea id="result-change-prompt" value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder={placeholder} rows={2} maxLength={5000} disabled={busy} className="min-w-0 flex-1 resize-y rounded-xl border border-white/10 bg-[#0b101b] px-4 py-3 text-sm leading-6 text-foreground outline-none focus:border-violet-400/50" /><button type="submit" aria-label="Prepare requested changes" disabled={!instruction.trim() || busy} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-violet-500 text-white hover:bg-violet-400 disabled:opacity-40">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-5 w-5" />}</button></div><p className="mt-2 text-[11px] leading-5 text-muted-foreground">{hint}</p>{error && <p role="alert" className="mt-2 text-xs text-amber-200">{error}</p>}</form>;
}
