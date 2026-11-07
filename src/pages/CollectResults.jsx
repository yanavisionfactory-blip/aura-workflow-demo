import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import WorkspaceShell from "@/components/aura/WorkspaceShell";
import SavedRunCollection from "@/components/aura/SavedRunCollection";
import { useAuth } from "@/lib/AuthContext";
import { getPythonRun, listPythonRuns } from "@/lib/auraApi";
import { aura } from "@/api/auraClient";
import { collectionActivity, parseRunCollection } from "@/lib/savedRunCollection.mjs";
import { toolResultName } from "@/lib/toolResultViews.mjs";
import { operationStepTitle } from "@/lib/planPresentation.mjs";

export default function CollectResults() {
  const navigate = useNavigate(), { workspace } = useAuth();
  const generation = useRef(0);
  const [runs, setRuns] = useState([]), [loaded, setLoaded] = useState({}), [selected, setSelected] = useState({});
  const [title, setTitle] = useState(""), [query, setQuery] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false), [preview, setPreview] = useState(null);
  useEffect(() => { generation.current += 1; let active = true; setRuns([]); setLoaded({}); setSelected({}); setPreview(null); if (workspace) listPythonRuns({ limit: 100 }).then((items) => { if (active) setRuns(items); }).catch(() => { if (active) setError("Could not load this workspace’s saved runs."); }); return () => { active = false; }; }, [workspace?.workspace_id]);
  const open = async (id) => { if (loaded[id]) return; setError(""); const version = generation.current; try { const run = await getPythonRun(id); if (version !== generation.current) return; setLoaded((old) => ({ ...old, [id]: run })); } catch { setError("This source run could not be loaded. Try again."); } };
  const prepare = () => { try {
    const sources = Object.entries(selected).filter(([, ids]) => ids.length).map(([runId, stepIds]) => ({ runId, stepIds }));
    const data = parseRunCollection({ kind: "saved_run_collection", title, sources });
    collectionActivity(data, Object.values(loaded)); setError(""); setPreview(data);
  } catch (problem) { setError(problem.message); } };
  const save = async () => { setBusy(true); setError(""); try { const saved = await aura.entities.Delivery.create(preview); navigate(`/results/${saved.id}`); } catch { setError("Could not save the collection. Your selection is preserved."); } finally { setBusy(false); } };
  return <WorkspaceShell onBack={() => navigate("/results")} onHistoryOpen={() => navigate("/", { state: { openHistory: true } })}>
    <div className="mx-auto w-full max-w-5xl px-4 py-8"><h1 className="text-2xl font-semibold">Bring your saved results together</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">Choose the completed actions that belong to this deliverable. AURA reads their saved results; it does not rerun any tools.</p>
      {error && <p role="alert" className="mt-4 text-sm text-amber-200">{error}</p>}
      {preview ? <div className="mt-5 flex gap-3"><button onClick={() => setPreview(null)} className="rounded-xl border border-white/15 px-4 py-3 text-sm">Edit selection</button><button onClick={save} disabled={busy} className="rounded-xl bg-primary px-4 py-3 text-sm font-semibold disabled:opacity-50">{busy ? "Saving…" : "Save results page"}</button></div> : <>
        <label className="mt-6 block text-sm">Result title<input value={title} onChange={(event) => setTitle(event.target.value)} className="mt-2 block w-full rounded-xl border border-white/15 bg-card p-3" placeholder="Campaign comparison report" maxLength={180} /></label>
        <label className="mt-5 block text-sm">Find a saved run<input value={query} onChange={(event) => setQuery(event.target.value)} className="mt-2 block w-full rounded-xl border border-white/15 bg-card p-3" placeholder="Search run names" /></label>
        <div className="mt-5 space-y-3">{runs.filter((run) => (run.plan?.name || run.name || run.prompt || "").toLowerCase().includes(query.toLowerCase())).map((run) => <details key={run.id} className="rounded-xl border border-white/10 p-4" onToggle={(event) => { if (event.currentTarget.open) open(run.id); }}><summary className="cursor-pointer text-sm font-medium">{run.plan?.name || run.name || run.prompt?.slice(0, 120) || "Saved run"}<span className="mt-1 block text-xs font-normal text-muted-foreground">{run.status.replaceAll("_", " ")} · {new Date(run.created_at).toLocaleString()}{selected[run.id]?.length ? ` · ${selected[run.id].length} selected` : ""}</span></summary>
          <div className="mt-4 space-y-3">{loaded[run.id] ? loaded[run.id].steps.filter((step) => step.status === "completed" && step.output?.provider_result).map((step) => <label key={step.id} className="flex items-start gap-3 rounded-lg bg-white/[0.03] p-3 text-sm"><input type="checkbox" checked={selected[run.id]?.includes(step.id) || false} onChange={(event) => setSelected((old) => ({ ...old, [run.id]: event.target.checked ? [...(old[run.id] || []), step.id] : (old[run.id] || []).filter((id) => id !== step.id) }))} className="mt-1" /><span>{toolResultName(step.tool_slug, step.operation)} · {operationStepTitle(step) || step.reason || "Saved action"}<span className="mt-1 block text-xs text-muted-foreground">{step.reason}</span></span></label>) : <p className="text-sm text-muted-foreground">Loading saved actions…</p>}</div>
        </details>)}</div>
        <button onClick={prepare} className="sticky bottom-4 mt-6 rounded-xl bg-primary px-5 py-3 text-sm font-semibold shadow-lg">Preview selected results ({Object.values(selected).flat().length})</button>
      </>}
    </div>{preview && <SavedRunCollection data={preview} />}
  </WorkspaceShell>;
}
