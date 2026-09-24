import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, CheckCircle2, RefreshCw, Pencil, ChevronDown, ChevronUp, MessageSquare, Users, Mail, FileText, BarChart3, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { aura } from "@/api/auraClient";
import { formatDistanceToNow } from "date-fns";
import { conjugateAction } from "@/lib/auraVerbs";
import { announceWorkflowHistoryChanged } from "@/lib/workflowHistory.mjs";
import { cancelPythonRun, dispatchDuePythonRun, getPythonRun, getPythonRunEvaluation, resumePythonRun } from "@/lib/auraApi";
import RunAgainModal from "./RunAgainModal";

const outcomeIcons = {
  message: MessageSquare,
  crm: Users,
  email: Mail,
  document: FileText,
  metric: BarChart3,
};

export default function HistoryRunDetail({ run, workflow, runCount = 1, onBack, onRerun, onEditRun }) {
  const [showSteps, setShowSteps] = useState(false);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(run.title || "");
  const [runAgainMode, setRunAgainMode] = useState(null); // null | "rerun" | "edit"
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelResult, setCancelResult] = useState("");
  const [checkBusy, setCheckBusy] = useState(false);
  const [checkResult, setCheckResult] = useState("");
  const [agentCheckBusy, setAgentCheckBusy] = useState(false);
  const [agentCheckResult, setAgentCheckResult] = useState("");
  const [repairReady, setRepairReady] = useState(false);
  const [reviewStepId, setReviewStepId] = useState(null);

  const requestRerun = (mode) => setRunAgainMode(mode);

  const checkAgentTeam = async () => {
    if (!run.backend_run_id || agentCheckBusy) return;
    setAgentCheckBusy(true);
    setAgentCheckResult("");
    try {
      const report = await getPythonRunEvaluation(run.backend_run_id);
      const team = report.agent_team;
      if (team?.passed) {
        setAgentCheckResult("Verified: the manager and execution agents handled each completed step, and the final result was confirmed.");
      } else if (report.status !== "completed") {
        setAgentCheckResult("This run has not reached a verified completion yet. Check again after it finishes.");
      } else {
        setAgentCheckResult("The workflow finished, but agent participation was not confirmed for every step. Some decisions may have used the safe fallback.");
      }
    } catch (error) {
      setAgentCheckResult(error.message || "Could not check agent participation for this run.");
    } finally {
      setAgentCheckBusy(false);
    }
  };

  const cancelRun = async () => {
    if (!run.backend_run_id || cancelBusy) return;
    setCancelBusy(true);
    setCancelResult("");
    try {
      const result = await cancelPythonRun(run.backend_run_id);
      setCancelResult(result.status === "cancelled"
        ? "Saved run cancelled."
        : result.cancellation_requested
          ? "Cancellation requested. AURA will stop before another step."
          : `Current run status: ${result.status}.`);
      if (result.status === "cancelled") {
        const updated = await aura.entities.WorkflowRun.update(run.id, { status: "cancelled" });
        announceWorkflowHistoryChanged({ run: updated });
      }
    } catch (error) {
      setCancelResult(error.message || "Could not cancel this saved run.");
    } finally {
      setCancelBusy(false);
    }
  };

  const checkPendingWork = async () => {
    if (!run.backend_run_id || checkBusy) return;
    setCheckBusy(true);
    setCheckResult("");
    setRepairReady(false);
    setReviewStepId(null);
    try {
      const result = await dispatchDuePythonRun(run.backend_run_id);
      const latest = await getPythonRun(run.backend_run_id);
      const blocked = result.preflight_blocker;
      // The public run view can say "recovering" while its durable status is
      // waiting_for_action. Use the scoped dispatch response to identify a pause.
      const paused = ["waiting_for_action", "failed"].includes(result.status);
      const recordedReceipt = latest.steps?.find((step) =>
        ["failed", "running"].includes(step.status)
        && step.consequential && step.output?.provider_result,
      );
      if (paused) {
        setReviewStepId(recordedReceipt?.id || null);
      }
      setRepairReady(blocked?.action === "wait_for_connector_repair" && result.preflight_status === "blocked");
      setCheckResult(blocked && result.preflight_status === "blocked"
        ? blocked.action === "wait_for_connector_repair"
          ? `Paused before step 1: ${blocked.tool_slug || "the selected app"} needs connector repair.`
          : `Paused before step 1: ${blocked.tool_slug || "the selected app"} needs ${blocked.action === "reconnect_account" ? "reconnection" : "attention"}.`
        : paused
          ? `Saved run paused: ${latest.error || recordedReceipt?.error || "This step needs attention."}${recordedReceipt ? " Its provider response is saved; a recheck will not repeat the action." : ""}`
        : result.published
        ? "Due work dispatched for this run."
        : result.next_attempt_at
          ? `Next retry: ${new Date(result.next_attempt_at).toLocaleString()}.`
          : `No due work for this run. Current status: ${result.status}.`);
    } catch (error) {
      setCheckResult(error.message || "Could not check this run.");
    } finally {
      setCheckBusy(false);
    }
  };

  const recheckRecordedResult = async () => {
    if (!run.backend_run_id || !reviewStepId || checkBusy) return;
    setCheckBusy(true);
    setCheckResult("");
    try {
      await resumePythonRun(run.backend_run_id, reviewStepId);
      setReviewStepId(null);
      setCheckResult("Rechecking the saved provider response on this run. No action was sent again.");
    } catch (error) {
      setCheckResult(error.message || "Could not recheck the saved response.");
    } finally {
      setCheckBusy(false);
    }
  };

  const recheckConnector = async () => {
    if (!run.backend_run_id || checkBusy) return;
    setCheckBusy(true);
    setCheckResult("");
    try {
      const result = await resumePythonRun(run.backend_run_id);
      setRepairReady(false);
      setCheckResult(result.preflight
        ? "Rechecking the repaired connector on this saved run. Check pending work for the latest result."
        : `Current run status: ${result.status}.`);
    } catch (error) {
      setCheckResult(error.message || "Could not recheck this connector.");
    } finally {
      setCheckBusy(false);
    }
  };

  const handleSave = async () => {
    const n = name.trim();
    if (!n || n === run.title) { setEditing(false); setName(run.title || ""); return; }
    try {
      const updated = await aura.entities.WorkflowRun.update(run.id, { title: n });
      announceWorkflowHistoryChanged({ run: updated });
    } catch (e) { /* ignore */ }
    setEditing(false);
  };

  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="flex flex-col h-full">
      {/* Back + meta */}
      <div className="px-4 pt-4 pb-3 border-b border-white/5">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mb-3 max-w-full"
          title={workflow ? `Back to ${workflow.name}` : "Back to history"}
        >
          <ArrowLeft className="w-3.5 h-3.5 flex-shrink-0" />
          <span className="truncate">{workflow ? workflow.name : "Back to history"}</span>
        </button>
        {editing ? (
          <div className="flex items-center gap-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSave(); if (e.key === "Escape") { setEditing(false); setName(run.title || ""); } }}
              autoFocus
              className="flex-1 bg-card/70 border border-primary/30 rounded-lg px-2.5 py-1.5 text-sm font-semibold outline-none focus:border-primary/50"
            />
            <button onClick={handleSave} className="p-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
              <Check className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => { setEditing(false); setName(run.title || ""); }} className="p-1.5 rounded-lg border border-white/10 text-muted-foreground hover:text-foreground transition-colors">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold leading-snug">{run.title || "Workflow"}</h2>
            <button onClick={() => { setName(run.title || ""); setEditing(true); }} className="p-1 rounded-lg text-muted-foreground/50 hover:text-foreground hover:bg-white/5 transition-colors" title="Rename workflow">
              <Pencil className="w-3 h-3" />
            </button>
          </div>
        )}
        <p className="text-xs text-muted-foreground mt-1">
          {formatDistanceToNow(new Date(run.backend_created_at || run.created_date), { addSuffix: true })}
          {run.duration_seconds ? ` · ${run.duration_seconds.toFixed(1)}s` : ""}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Summary */}
        {run.summary && (
          <div className="p-3 rounded-xl bg-emerald-400/5 border border-emerald-400/15">
            <div className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-foreground/80 leading-relaxed">{run.summary}</p>
            </div>
          </div>
        )}

        {/* Metrics */}
        {run.metrics?.length > 0 && (
          <div className="grid grid-cols-3 gap-2">
            {run.metrics.map((m, i) => (
              <div key={i} className="p-3 rounded-xl border border-white/5 bg-card/40 text-center">
                <div className="text-lg font-bold text-gradient">{m.value}</div>
                <div className="text-[10px] text-muted-foreground mt-0.5">{m.label}</div>
              </div>
            ))}
          </div>
        )}

        {/* What AURA did */}
        {run.outcomes?.length > 0 && (
          <div>
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground/50 font-medium mb-2">What was done</p>
            <div className="space-y-2">
              {run.outcomes.map((o, i) => {
                const Icon = outcomeIcons[o.type] || CheckCircle2;
                return (
                  <div key={i} className="flex items-start gap-2.5 p-3 rounded-xl border border-white/5 bg-card/30">
                    <div className="p-1 rounded-lg bg-primary/10 flex-shrink-0">
                      <Icon className="w-3.5 h-3.5 text-primary" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">{o.title}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">{o.detail}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Notes */}
        {run.notes && (
          <div className="p-3 rounded-xl bg-amber-400/5 border border-amber-400/15">
            <p className="text-xs text-amber-300/80">{run.notes}</p>
          </div>
        )}

        {/* Steps — hidden by default */}
        {run.steps?.length > 0 && (
          <div>
            <button
              onClick={() => setShowSteps(!showSteps)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {showSteps ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              {showSteps ? "Hide" : "Show"} step-by-step details
            </button>
            {showSteps && (
              <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} className="mt-2 space-y-1.5">
                {run.steps.map((step, i) => (
                  <div key={i} className="flex items-start gap-2.5 p-2.5 rounded-lg border border-white/5 bg-card/20">
                    <span className="text-[10px] text-muted-foreground/40 mt-0.5 w-4 flex-shrink-0">{i + 1}</span>
                    <div>
                      <span className="text-[11px] font-medium text-muted-foreground/60">{step.tool}</span>
                      <p className="text-xs mt-0.5">{conjugateAction(step.action, "past")}</p>
                    </div>
                  </div>
                ))}
              </motion.div>
            )}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="p-4 border-t border-white/5">
        {run.backend_run_id && (
          <div className="mb-3 space-y-2">
            <Button size="sm" variant="outline" className="w-full border-white/15"
              onClick={checkAgentTeam} disabled={agentCheckBusy}>
              {agentCheckBusy ? "Checking agent teamwork…" : "Verify agent teamwork"}
            </Button>
            {agentCheckResult && <p role="status" className="text-xs text-muted-foreground">{agentCheckResult}</p>}
          </div>
        )}
        {run.status === "running" && run.backend_run_id && (
          <div className="mb-3 space-y-2">
            <Button size="sm" variant="outline" className="w-full border-white/15"
              onClick={checkPendingWork} disabled={checkBusy}>
              {checkBusy ? "Checking this run…" : "Check pending work"}
            </Button>
            {checkResult && <p role="status" className="text-xs text-muted-foreground">{checkResult}</p>}
            {repairReady && (
              <Button size="sm" variant="outline" className="w-full border-amber-400/25 text-amber-200"
                onClick={recheckConnector} disabled={checkBusy}>
                Recheck connector on this run
              </Button>
            )}
            {reviewStepId && (
              <Button size="sm" variant="outline" className="w-full border-amber-400/25 text-amber-200"
                onClick={recheckRecordedResult} disabled={checkBusy}>
                Recheck saved provider result
              </Button>
            )}
            <Button size="sm" variant="outline" className="w-full border-rose-400/25 text-rose-300"
              onClick={cancelRun} disabled={cancelBusy || Boolean(cancelResult && !cancelResult.startsWith("Could not"))}>
              {cancelBusy ? "Cancelling saved run…" : "Cancel saved run"}
            </Button>
            {cancelResult && <p role="status" className="mt-2 text-xs text-muted-foreground">{cancelResult}</p>}
          </div>
        )}
        {runAgainMode ? (
          <RunAgainModal
            open
            mode={runAgainMode}
            run={workflow ? { ...workflow, title: workflow.name } : run}
            runCount={runCount}
            onClose={() => setRunAgainMode(null)}
            onConfirm={(_prompt, approval) => {
              const mode = runAgainMode;
              setRunAgainMode(null);
              if (mode === "edit") onEditRun?.(approval);
              else onRerun?.(approval);
            }}
          />
        ) : (
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              className="flex-1 border-white/10 hover:bg-white/5 text-xs gap-1.5"
              onClick={() => requestRerun("rerun")}
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Run again
            </Button>
            <Button
              size="sm"
              className="flex-1 bg-primary/90 hover:bg-primary text-xs gap-1.5"
              onClick={() => setRunAgainMode("edit")}
            >
              <Pencil className="w-3.5 h-3.5" />
              Edit & run again
            </Button>
          </div>
        )}
      </div>
    </motion.div>
  );
}
