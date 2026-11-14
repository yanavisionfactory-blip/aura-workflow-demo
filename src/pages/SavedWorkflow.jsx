import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import WorkspaceShell from "@/components/aura/WorkspaceShell";
import { useAuth } from "@/lib/AuthContext";
import { createPythonRun, getPythonWorkflow } from "@/lib/auraApi";

export default function SavedWorkflow() {
  const { workflowId } = useParams();
  const navigate = useNavigate();
  const { workspace, user, isLoadingWorkspace, workspaceError } = useAuth();
  const scope = `${workspace?.workspace_id || ""}:${workflowId}:${isLoadingWorkspace ? "loading" : "ready"}`;
  const [loaded, setLoaded] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retry, setRetry] = useState(0);
  const [building, setBuilding] = useState(false);
  const pending = useRef(false);
  const request = useRef(null);
  const generation = useRef(0);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const workflow = workspace && !isLoadingWorkspace && loaded?.scope === scope ? loaded.workflow : null;
  const error = failure?.scope === scope ? failure.message : "";

  useEffect(() => {
    let active = true;
    generation.current += 1;
    setLoaded(null); setFailure(null); setBuilding(false);
    pending.current = false; request.current = null;
    if (!workspace || isLoadingWorkspace) return () => { active = false; generation.current += 1; };
    getPythonWorkflow(workflowId)
      .then((value) => { if (active) setLoaded({ scope, workflow: value }); })
      .catch((reason) => { if (active) setFailure({ scope, message:
        reason.status === 404 || reason.status === 403
          ? "This saved task is not available in your current workspace. Check Account to confirm your sign-in and workspace."
          : reason.status === 401 ? "Your session could not be verified. Open Account to sign in again."
            : "AURA could not load this saved task. Please try again.",
      }); });
    return () => { active = false; generation.current += 1; };
  }, [scope, isLoadingWorkspace, retry]);

  const buildPlan = async () => {
    if (!workflow || pending.current) return;
    pending.current = true; setBuilding(true); setFailure(null);
    const startedScope = scope;
    const startedGeneration = generation.current;
    const isCurrent = () => currentScope.current === startedScope && generation.current === startedGeneration;
    // Reuse the same key after an ambiguous response; opening the link itself
    // never creates a run, approves a plan, or enables the saved workflow.
    request.current ||= crypto.randomUUID();
    try {
      // A disabled draft is a source for a fresh proposal, not an enabled
      // automation. Do not change its enabled flag or execute its saved plan.
      const run = await createPythonRun(workflow.prompt, null, request.current);
      if (isCurrent()) navigate("/", { state: { resumeRunId: run.id } });
    } catch {
      if (isCurrent()) setFailure({ scope, message:
        "AURA could not confirm that planning started. Try again to check the same request.",
      });
    } finally {
      if (isCurrent()) { pending.current = false; setBuilding(false); }
    }
  };

  return <WorkspaceShell onBack={() => navigate("/", { state: { newWorkflow: true } })}
    onHistoryOpen={() => navigate("/", { state: { openHistory: true } })}>
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-12">
      {workflow ? <section className="rounded-2xl border border-white/10 bg-white/[0.025] p-6 md:p-8">
        <p className="text-xs font-semibold uppercase tracking-widest text-violet-300">Saved task</p>
        <h1 className="mt-3 text-2xl font-semibold">{workflow.name}</h1>
        <p className="mt-3 text-sm text-muted-foreground">Build a plan from this task, review its steps, then choose Start in AURA.</p>
        <div className="mt-6 whitespace-pre-wrap break-words rounded-xl border border-white/10 bg-black/20 p-4 text-sm leading-7">{workflow.prompt}</div>
        {error && <p role="alert" className="mt-4 text-sm text-amber-200">{error}</p>}
        <button type="button" disabled={building} onClick={buildPlan}
          className="mt-6 rounded-xl bg-violet-500 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50">
          {building ? "Building your plan…" : "Build the plan"}
        </button>
      </section> : <section className="py-14 text-center text-sm text-muted-foreground">
        <p role={error || workspaceError ? "alert" : "status"}>{error || (workspaceError
          ? "Your workspace could not be loaded. Use Retry now below." : "Opening your saved task…")}</p>
        {error && <><p className="mt-3">Signed in as {user?.primaryEmailAddress?.emailAddress || "your current account"} · {workspace?.name}</p>
          <button type="button" onClick={() => setRetry((value) => value + 1)}
            className="mt-4 rounded-lg border border-primary/30 px-4 py-2 text-primary">Retry loading task</button></>}
      </section>}
    </main>
  </WorkspaceShell>;
}
