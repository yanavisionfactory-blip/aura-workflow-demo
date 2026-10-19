import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import WorkspaceShell from "@/components/aura/WorkspaceShell";
import SeoAuditResult from "@/components/aura/SeoAuditResult";
import { getPythonRun } from "@/lib/auraApi";
import { crawlInventory } from "@/lib/seoAuditResult.mjs";
import { buildSeoAuditDemo, seoAuditDemoRoute } from "@/lib/seoAuditDemo.mjs";

const decode = (value) => new TextDecoder().decode(Uint8Array.from(atob(value), (char) => char.charCodeAt(0)));

export default function SeoAuditDemo() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setRun(null); setError("");
    if (!seoAuditDemoRoute(runId)) { setError("Choose a valid saved crawl analysis."); return undefined; }
    // Same authenticated API as saved results. No provider requests or writes.
    getPythonRun(runId).then((value) => { if (active) setRun(value); })
      .catch(() => { if (active) setError("The real crawl is unavailable in this workspace. Sign in to the workspace that imported the Screaming Frog exports, then retry."); });
    return () => { active = false; };
  }, [runId, attempt]);
  const result = useMemo(() => {
    if (!run) return {};
    try { return { demo: buildSeoAuditDemo(run, crawlInventory(run, decode)) }; }
    catch (failure) { return { error: failure.message }; }
  }, [run]);
  return <WorkspaceShell onBack={() => navigate("/")} onHistoryOpen={() => navigate("/", { state: { openHistory: true } })}>
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8 md:py-12">
      {result.demo ? <SeoAuditResult manifest={result.demo.manifest} demo={result.demo} /> : <div role={error || result.error ? "alert" : "status"} className="rounded-2xl border border-white/10 p-8 text-center text-sm text-muted-foreground"><p>{error || result.error || "Opening the real Screaming Frog data and preparing the labelled demo…"}</p>{error && <button type="button" onClick={() => setAttempt((value) => value + 1)} className="mt-4 rounded-lg border border-primary/30 px-4 py-2 text-primary">Retry</button>}</div>}
      <div className="mt-8 flex flex-wrap justify-center gap-5 border-t border-white/10 pt-5 text-xs text-muted-foreground"><Link to={`/runs/${encodeURIComponent(runId)}`} className="text-primary">Open original Screaming Frog result</Link><button type="button" onClick={() => navigate("/", { state: { newWorkflow: true } })}>New workflow</button></div>
    </main>
  </WorkspaceShell>;
}
