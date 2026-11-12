import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import WorkspaceShell from "@/components/aura/WorkspaceShell";
import ResultsView from "@/components/aura/ResultsView";
import { getPythonRun } from "@/lib/auraApi";
import { savedRunResults } from "@/lib/savedRunResults.mjs";
import { operationStepTitle } from "@/lib/planPresentation.mjs";
import { savedRunActionLocation, savedRunResumeView } from "@/lib/runtimePlan.mjs";
import { toolResultName } from "@/lib/toolResultViews.mjs";
import { useAuth } from "@/lib/AuthContext";
import { attachedDocumentsFromRun } from "@/lib/runAttachments.mjs";
import { replaceAttachedDocuments } from "@/lib/documentStore";
import Demo from "@/pages/Demo";

export default function SavedRunResults({ recovery = false }) {
  const { runId } = useParams();
  const navigate = useNavigate();
  const { workspace, user, isLoadingWorkspace, workspaceError } = useAuth();
  const [loaded, setLoaded] = useState(null);
  const scope = `${workspace?.workspace_id || ""}:${runId}:${recovery ? "recovery" : "results"}`;
  const run = workspace && !isLoadingWorkspace && loaded?.scope === scope ? loaded.run : null;
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setLoaded(null); setError("");
    if (!workspace || isLoadingWorkspace) return () => { active = false; };
    getPythonRun(runId).then((value) => { if (active) setLoaded({ scope, run: value }); })
      .catch((failure) => { if (active) setError(
        failure.status === 404 || failure.status === 403
          ? "This saved run is not available in your current workspace. Check Account to confirm your sign-in and workspace. A run link does not grant access."
          : failure.status === 401 ? "Your session could not be verified. Open Account to sign in again."
            : "AURA could not load this workflow. Retry when your connection is available."
      ); });
    return () => { active = false; };
  }, [scope, isLoadingWorkspace, retry]);
  // Opening a recovery URL is read-only. Only a blocked execution enters the
  // existing recovery screen; active and completed runs retain their results.
  if (recovery && run && savedRunResumeView(run) === "recovery") {
    return <Demo key={scope} initialRecoveryRun={run} />;
  }
  const openRun = () => {
    if (savedRunResumeView(run) === "recovery") navigate(`/runs/${run.id}/recover`);
    else navigate("/", { state: { resumeRunId: run.id } });
  };
  const activity = (run?.steps || []).map((step) => {
    const tool = toolResultName(step.tool_slug, step.operation);
    return { id: step.id, stepKey: step.key, tool, status: step.status,
      operation: step.operation, arguments: step.arguments, error: step.error,
      started_at: step.started_at, completed_at: step.completed_at,
      action: operationStepTitle(step, tool) || step.reason || "Saved action", output: step.output, liveOutput: step.status === "completed" ? "Completed" : "" };
  });
  return <WorkspaceShell onBack={() => navigate("/")} onHistoryOpen={() => navigate("/", { state: { openHistory: true } })}>
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 md:py-10">
      {run ? <ResultsView results={savedRunResults(run)} activity={activity} prompt={run.prompt} backendRunId={run.id}
        onOpenRun={openRun}
        onNewWorkflow={() => navigate("/", { state: { newWorkflow: true } })}
        onRepeatWorkflow={(prompt) => {
          replaceAttachedDocuments(attachedDocumentsFromRun(run));
          const next = savedRunActionLocation(prompt);
          navigate(next.pathname, { state: next.state });
        }}
        onStartWorkflow={(prompt) => {
          const next = savedRunActionLocation(prompt);
          navigate(next.pathname, { state: next.state });
        }} />
        : <section className="py-14 text-center text-sm text-muted-foreground">
          <p role={error || workspaceError ? "alert" : "status"}>{error || (workspaceError ? "Your workspace could not be loaded. Use Retry now below." : recovery ? "Opening workflow recovery…" : "Opening your saved workflow results…")}</p>
          {error && <><p className="mt-3">Signed in as {user?.primaryEmailAddress?.emailAddress || "your current account"} · {workspace?.name}</p>
            <button type="button" onClick={() => setRetry((value) => value + 1)} className="mt-4 rounded-lg border border-primary/30 px-4 py-2 text-primary">{recovery ? "Retry loading workflow" : "Retry loading results"}</button></>}
        </section>}
      {run && run.status !== "completed" && <details aria-label="Current run status" className="mx-auto max-w-3xl rounded-xl border border-white/10 p-4 text-xs text-muted-foreground">
        <summary className="cursor-pointer font-medium">Run details</summary>
        <div className="mt-3 space-y-2">
          <p>Current status: {run.status.replaceAll("_", " ")}</p>
          {run.blocker?.message && <p>{run.blocker.message}</p>}
          {run.error && <p>{run.error}</p>}
          {run.automation_state?.message && <p>{run.automation_state.message}</p>}
          <button type="button" onClick={openRun} className="rounded-lg border border-primary/30 px-3 py-2 font-semibold text-primary">Open live workflow</button>
        </div>
      </details>}
    </main>
  </WorkspaceShell>;
}
