import { useEffect, useState } from "react";
import { editedArgumentsForStep } from "@/lib/approvalReview.mjs";
import { auraRequest } from "@/lib/auraApi";

export default function RunReadiness({ runId, plan, backendPlan, steps, onReady }) {
  const reviewBody = JSON.stringify({ edited_steps: backendPlan?.steps?.map((step, index) => (
    steps?.[index] ? { ...step, arguments: editedArgumentsForStep(steps[index]) } : step
  )) });
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let live = true;
    let timer;
    onReady(false); setBusy(true); setError(""); setReport(null);
    auraRequest(`/v1/runs/${encodeURIComponent(runId)}/preflight`, { method: "POST", body: reviewBody, timeoutMs: 60000 })
      .then((data) => {
        if (!live) return;
        setReport(data); onReady(data.passed);
        timer = window.setTimeout(() => { if (live) onReady(false); }, Math.max(0, Date.parse(data.expires_at) - Date.now()));
      }).catch((err) => { if (live) setError(err.message); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; window.clearTimeout(timer); };
  }, [runId, plan, reviewBody, revision, onReady]);
  return <section aria-live="polite" className="my-4 rounded-xl border border-white/10 p-4 text-sm">
    <h3 className="font-semibold">Account and destination checks</h3>
    <p className="mt-1 text-xs text-muted-foreground">AURA checks this plan’s required access before Start and again before execution. New destinations are verified after creation.</p>
    {busy && <p className="mt-2">Checking the selected accounts…</p>}
    {error && <p role="alert" className="mt-2 text-amber-300">{error}</p>}
    <ul className="mt-2 space-y-2">{report?.checks?.map((check, i) => <li key={i}>{check.status === "passed" ? "✓ " : "! "}{check.message}{check.connected_account && <span className="block text-xs text-muted-foreground">Account: {check.connected_account}</span>}</li>)}</ul>
    {report && <p className="mt-2 text-xs text-muted-foreground">Checked {new Date(report.checked_at).toLocaleTimeString()}. Checks expire after one minute; check again if Start becomes unavailable.</p>}
    <button type="button" disabled={busy} className="mt-3 underline disabled:opacity-50" onClick={() => setRevision((v) => v + 1)}>Check again</button>
  </section>;
}
