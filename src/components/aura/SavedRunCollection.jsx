import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getPythonRun } from "@/lib/auraApi";
import { useAuth } from "@/lib/AuthContext";
import { collectionActivity, collectionResults } from "@/lib/savedRunCollection.mjs";
import ResultsView from "./ResultsView";

export default function SavedRunCollection({ data }) {
  const navigate = useNavigate();
  const { workspace } = useAuth();
  const [loaded, setLoaded] = useState(null), [error, setError] = useState("");
  useEffect(() => {
    let active = true; setLoaded(null); setError("");
    if (!workspace) return;
    Promise.all(data.sources.map(({ runId }) => getPythonRun(runId))).then((runs) => {
      const activity = collectionActivity(data, runs);
      if (active) setLoaded({ activity, results: collectionResults(data, activity), runs });
    }).catch(() => { if (active) setError("These source results are unavailable in your current workspace. Check Account and reopen the saved collection."); });
    return () => { active = false; };
  }, [data, workspace?.workspace_id]);
  return <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:py-10">{loaded ? <>
    <ResultsView results={loaded.results} activity={loaded.activity} onNewWorkflow={() => navigate("/")} onStartWorkflow={() => navigate("/")} />
    <details className="mx-auto max-w-5xl rounded-xl border border-white/10 p-4 text-xs text-muted-foreground"><summary className="cursor-pointer">Source runs · {loaded.runs.length}</summary><ul className="mt-3 space-y-3">{loaded.runs.map((run) => <li key={run.id}><a href={`#/runs/${run.id}`} className="text-cyan-200 underline underline-offset-4">{run.plan?.name || "Saved workflow"}</a><span className="mt-1 block">Original run: {run.status.replaceAll("_", " ")} · Only selected completed actions are included above.</span></li>)}</ul></details>
  </> : <p role={error ? "alert" : "status"} className="py-12 text-center text-sm text-muted-foreground">{error || "Loading the saved outputs from your workspace…"}</p>}</main>;
}
