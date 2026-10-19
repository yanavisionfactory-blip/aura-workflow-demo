import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import WorkspaceShell from "@/components/aura/WorkspaceShell";
import ResultsView from "@/components/aura/ResultsView";
import { getPythonRun } from "@/lib/auraApi";
import { savedRunResults } from "@/lib/savedRunResults.mjs";
import { operationStepTitle } from "@/lib/planPresentation.mjs";

export default function SavedRunResults() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setRun(null); setError("");
    getPythonRun(runId).then((value) => { if (active) setRun(value); })
      .catch(() => { if (active) setError("These saved results are unavailable in this workspace. Open My workflows to choose an accessible run."); });
    return () => { active = false; };
  }, [runId]);
  const names = { "google-docs": "Google Docs", google: "Google Workspace" };
  const activity = (run?.steps || []).map((step) => {
    const tool = names[step.tool_slug] || step.tool_slug || "AURA";
    return { id: step.id, stepKey: step.key, tool, status: step.status,
      operation: step.operation, arguments: step.arguments, error: step.error,
      started_at: step.started_at, completed_at: step.completed_at,
      action: operationStepTitle(step, tool) || step.reason || "Saved action", output: step.output, liveOutput: step.status === "completed" ? "Completed" : "" };
  });
  return <WorkspaceShell onBack={() => navigate("/")} onHistoryOpen={() => navigate("/", { state: { openHistory: true } })}>
    <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 md:py-12">
      {run && run.status !== "completed" && <section aria-label="Current run status" className="mb-6 rounded-2xl border border-amber-300/20 bg-amber-300/5 p-5 text-sm">
        <h2 className="font-semibold">Current status: {run.status.replaceAll("_", " ")}</h2>
        {run.blocker?.message && <p className="mt-2">{run.blocker.message}</p>}
        {run.error && <p className="mt-2">{run.error}</p>}
        {run.automation_state && <div className="mt-3 space-y-2 text-muted-foreground">
          <p>Connection checks: {run.automation_state.status || "pending"}{run.automation_state.attempt ? ` · attempt ${run.automation_state.attempt}` : ""}</p>
          {run.automation_state.message && <p>{run.automation_state.message}</p>}
          {run.automation_state.next_attempt_at && <p>Next check: {run.automation_state.next_attempt_at}</p>}
          {(run.automation_state.checks || []).map((check, index) => <p key={index}>{check.tool_slug || check.type}: {check.status}{check.connected_account ? ` · ${check.connected_account}` : ""}</p>)}
        </div>}
      </section>}
      {run ? <ResultsView results={savedRunResults(run)} activity={activity} prompt={run.prompt} backendRunId={run.id}
        onNewWorkflow={() => navigate("/", { state: { newWorkflow: true } })} onStartWorkflow={() => navigate("/", { state: { newWorkflow: true } })} />
        : <p role={error ? "alert" : "status"} className="py-14 text-center text-sm text-muted-foreground">{error || "Opening your saved workflow results…"}</p>}
    </main>
  </WorkspaceShell>;
}
