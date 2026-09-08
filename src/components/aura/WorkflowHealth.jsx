import { useEffect, useState } from "react";
import { auraRequest, ensureWorkspace } from "@/lib/auraApi";

export default function WorkflowHealth({ onClose }) {
  const [matrix, setMatrix] = useState(null);
  const [health, setHealth] = useState(null);
  const [performance, setPerformance] = useState(null);
  const [probe, setProbe] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function refresh() {
    await ensureWorkspace();
    const results = await Promise.allSettled([
      auraRequest("/v1/assurance/operations"), auraRequest("/v1/assurance/operations-health"),
      auraRequest("/v1/assurance/performance"), auraRequest("/v1/assurance/recovery-probes"),
    ]);
    if (results[0].status === "fulfilled") setMatrix(results[0].value);
    else setError(results[0].reason.message);
    if (results[1].status === "fulfilled") setHealth(results[1].value);
    if (results[2].status === "fulfilled") setPerformance(results[2].value);
    if (results[3].status === "fulfilled" && results[3].value.probes.length) setProbe(results[3].value.probes[0]);
  }
  useEffect(() => { refresh().catch(e => setError(e.message)); }, []);
  useEffect(() => {
    if (!probe?.probe_id || probe.passed || ["failed", "blocked", "waiting_for_action"].includes(probe.status)) return;
    const id = window.setInterval(() => auraRequest(`/v1/assurance/recovery-probes/${probe.probe_id}`).then(setProbe).catch(e => setError(e.message)), 5000);
    return () => window.clearInterval(id);
  }, [probe?.probe_id, probe?.status, probe?.passed]);
  async function startProbe() {
    setBusy(true); setError("");
    try { setProbe(await auraRequest("/v1/assurance/recovery-probes", { method: "POST" })); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function importEvidence(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true); setError("");
    try {
      if (file.size > 1000000) throw new Error("Evidence file is too large");
      const payload = JSON.parse(await file.text());
      await auraRequest("/v1/assurance/certifications", { method: "POST", body: JSON.stringify(payload) });
      await refresh();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); event.target.value = ""; }
  }
  return <div className="fixed inset-0 z-50 bg-black/70 p-4 overflow-y-auto" role="dialog" aria-modal="true" aria-labelledby="workflow-health-title">
    <section className="max-w-5xl mx-auto my-6 rounded-2xl border border-white/15 bg-background p-6 shadow-xl">
      <div className="flex justify-between gap-4 items-start"><div><h2 id="workflow-health-title" className="text-xl font-semibold">Workflow health</h2>
        <p className="text-sm text-muted-foreground mt-1">Readiness is assessed for each operation. Connected apps still need live certification for unattended execution.</p></div>
        <button onClick={onClose} className="px-3 py-2 border rounded-lg">Close</button></div>
      {error && <p role="alert" className="mt-4 text-red-400">{error}</p>}
      {!matrix && !error && <p className="mt-6">Loading workspace evidence…</p>}
      {matrix && <><h3 className="font-semibold mt-6">Operation readiness</h3><p className="text-sm mb-3">{matrix.certified} of {matrix.total} operations certified</p>
        <div className="overflow-x-auto max-h-80 overflow-y-auto"><table className="w-full text-sm text-left"><thead><tr><th className="p-2">App / operation</th><th className="p-2">Status</th><th className="p-2">Remaining evidence</th></tr></thead><tbody>
          {matrix.operations.map(row => <tr className="border-t border-white/10" key={`${row.tool_id}:${row.operation}`}><td className="p-2">{row.connector}<br/><span className="text-xs text-muted-foreground">{row.operation}</span></td><td className="p-2">{row.status}</td><td className="p-2">{row.reasons.join("; ") || "Current certification passed"}</td></tr>)}
        </tbody></table></div></>}
      {health && <><div className="mt-6 flex justify-between items-center"><h3 className="font-semibold">Runs needing attention</h3><button onClick={() => refresh().catch(e => setError(e.message))} className="border rounded-lg px-3 py-1">Refresh health</button></div>
        {health.runs.length === 0 ? <p className="text-sm mt-2">No active or blocked runs in this view.</p> : <ul className="text-sm divide-y divide-white/10">{health.runs.map(run => <li key={run.run_id} className="py-3 flex justify-between gap-4"><div>{run.status}{run.stale ? " · stale" : ""}<p className="text-muted-foreground">{run.diagnostic.next_action || "Execution is in progress."}</p></div><button onClick={() => auraRequest(`/v1/runs/${run.run_id}/diagnostics`).then(setDetail).catch(e => setError(e.message))}>Inspect run</button></li>)}</ul>}
        {detail && <div className="bg-white/5 rounded-lg p-3 mt-3 text-sm"><p>Run: {detail.run_id}</p><p>{detail.next_action}</p><p>Responsible: {detail.owner || "none"} · Recorded attempts: {detail.attempts.length}</p></div>}
        <h3 className="font-semibold mt-6">Recovery validation</h3><p className="text-sm text-muted-foreground mt-1">Creates a dedicated public-weather workflow, saves its first result, and yields it for scheduler recovery. It also checks approval-paused and completed guard runs. Uses public reads and model calls.</p>
        <button disabled={busy || (probe && !probe.passed && ["running", "recovering"].includes(probe.status))} onClick={startProbe} className="mt-3 border rounded-lg px-4 py-2 disabled:opacity-50">Run read-only recovery check</button>
        {probe && <div className="mt-3 text-sm" aria-live="polite"><p>Recovery check: {probe.passed ? "Passed" : probe.status}</p><p>Checkpoint saved: {probe.yielded_at ? "yes" : "pending"} · Scheduler recovery observed: {probe.recovery_observed ? "yes" : "pending"}</p><p>Provider attempts: {Object.entries(probe.provider_attempts || {}).map(([k,v]) => `${k}: ${v}`).join(", ")}</p><p>Guard runs unchanged: {Object.values(probe.guards_unchanged || {}).every(Boolean) ? "yes" : "no"}</p>{probe.error && <p>{probe.error}</p>}</div>}
        <h3 className="font-semibold mt-6">Certification evidence</h3><p className="text-sm text-muted-foreground">Import a signed report from the dedicated-account certification runner. Partial, expired or mismatched evidence is rejected.</p><input className="mt-3 text-sm" type="file" accept="application/json,.json" aria-label="Import signed certification evidence" onChange={importEvidence} disabled={busy}/></>}
      {performance && <><h3 className="font-semibold mt-6">Observed performance</h3><p className="text-sm">{performance.runs_sampled} recent runs · {performance.status.replaceAll("_", " ")}</p><p className="text-xs text-muted-foreground">A baseline is not load certification. Percentiles use the available measurements; completion wall time includes approval waits.</p><table className="text-sm w-full mt-2"><thead><tr><th className="text-left">Metric</th><th>Samples</th><th>p50</th><th>p95</th></tr></thead><tbody>{Object.entries(performance.metrics).map(([key,m]) => <tr key={key}><td className="py-1">{key.replaceAll("_", " ")}</td><td className="text-center">{m.samples}</td><td className="text-center">{m.p50 == null ? "—" : Math.round(m.p50)}</td><td className="text-center">{m.p95 == null ? "—" : Math.round(m.p95)}</td></tr>)}</tbody></table></>}
    </section>
  </div>;
}
