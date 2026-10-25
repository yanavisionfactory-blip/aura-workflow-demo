import { useEffect, useState } from "react";
import { auraRequest } from "@/lib/auraApi";

export default function RunSupportAccess({ runId }) {
  const [open, setOpen] = useState(false);
  const [consent, setConsent] = useState(false);
  const [grants, setGrants] = useState([]);
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const endpoint = `/v1/runs/${encodeURIComponent(runId)}/support-grants`;
  useEffect(() => {
    if (!open || !runId) return;
    let live = true;
    auraRequest(endpoint).then((r) => { if (live) setGrants(r.grants); }).catch((e) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [open, runId, endpoint]);
  if (!runId) return null;
  return <section className="my-4 rounded-xl border border-white/10 p-4 text-sm">
    <button type="button" onClick={() => setOpen(!open)} className="font-medium">Get help with this run</button>
    {open && <div className="mt-3 space-y-3">
      <p className="text-muted-foreground">Share this run’s status, operation names and whether receipts and verification were saved. Prompts, account details, sheet contents and credentials are excluded. Anyone with the link can read these diagnostics until it expires or you revoke it. The link cannot change or resume your run.</p>
      <label className="flex gap-2"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />I agree to share these diagnostics for 30 minutes.</label>
      <button type="button" disabled={!consent || busy} className="rounded-lg bg-primary px-3 py-2 text-white disabled:opacity-40" onClick={async () => {
        setBusy(true); setError("");
        try {
          const grant = await auraRequest(endpoint, { method: "POST", body: JSON.stringify({ consent: true, minutes: 30 }) });
          setGrants((old) => [...old, grant]);
          setLink(`${window.location.origin}${import.meta.env.BASE_URL}support/runs/${encodeURIComponent(grant.id)}#access_token=${encodeURIComponent(grant.access_token)}`);
        } catch (e) { setError(e.message); } finally { setBusy(false); }
      }}>Create temporary support link</button>
      {link && <div><label>Support link<input readOnly value={link} className="mt-1 w-full rounded border bg-background p-2" onFocus={(e) => e.target.select()} /></label><button type="button" className="mt-2 underline" onClick={() => navigator.clipboard.writeText(link).catch(() => setError("Select and copy the support link above."))}>Copy link</button></div>}
      {grants.map((grant) => <div key={grant.id} className="flex items-center justify-between gap-2"><span>Expires {new Date(grant.expires_at).toLocaleTimeString()}</span><button type="button" className="underline" onClick={async () => {
        try { await auraRequest(`${endpoint}/${encodeURIComponent(grant.id)}`, { method: "DELETE" }); setGrants((old) => old.filter((g) => g.id !== grant.id)); if (link.includes(grant.id)) setLink(""); } catch (e) { setError(e.message); }
      }}>Revoke</button></div>)}
      {error && <p role="alert" className="text-amber-300">{error}</p>}
    </div>}
  </section>;
}
