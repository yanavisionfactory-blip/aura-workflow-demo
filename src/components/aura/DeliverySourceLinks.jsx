import { useState } from "react";
import { Link2 } from "lucide-react";
import { deliverySourceLinks } from "@/lib/workflowDelivery.mjs";

export default function DeliverySourceLinks({ values = {}, onSave }) {
  const [links, setLinks] = useState(values);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  return <details className="group mt-4 text-xs text-muted-foreground">
    <summary className="flex w-fit cursor-pointer list-none items-center gap-1.5 hover:text-foreground [&::-webkit-details-marker]:hidden"><Link2 className="h-3.5 w-3.5" />Manage output links</summary>
    <form className="mt-4 space-y-4 rounded-2xl border border-white/10 bg-card/60 p-5" onSubmit={async (event) => {
      event.preventDefault(); if (saving) return; setError(""); setSaved(false); setSaving(true);
      try { const next = deliverySourceLinks(links); await onSave(next); setSaved(true); }
      catch { setError("The links couldn't be saved. Check the document URLs and try again."); }
      finally { setSaving(false); }
    }}>
      <p>Link the existing saved documents. This updates links on this results page.</p>
      {[["intake", "Intake document"], ["research", "Keyword research document"], ["report", "Final report document"]].map(([key, label]) => <label key={key} className="block space-y-2"><span>{label}</span><input aria-label={label} type="url" value={links[key] || ""} onChange={(event) => setLinks((current) => ({ ...current, [key]: event.target.value }))} disabled={saving} placeholder="https://docs.google.com/document/d/…/edit" className="w-full rounded-lg border border-white/10 bg-background px-3 py-2.5 text-xs text-foreground outline-none focus:border-primary" /></label>)}
      {error && <p role="alert" className="text-amber-200">{error}</p>}
      {saved && <p role="status" className="text-emerald-300">Output links saved and verified.</p>}
      <button type="submit" disabled={saving} className="rounded-lg bg-primary px-4 py-2 font-medium text-white disabled:opacity-50">{saving ? "Saving links…" : "Save output links"}</button>
    </form>
  </details>;
}
