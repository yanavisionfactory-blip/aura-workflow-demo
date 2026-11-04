import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import { AlertTriangle, Brain, Plus, ArrowRight, Sparkles, Loader2, Check, X, RotateCcw } from "lucide-react";
import { aura } from "@/api/auraClient";
import RunReadiness from "./RunReadiness";
import RunSupportAccess from "./RunSupportAccess";
import PlanStep from "./PlanStep";
import PlanConnectionAlert from "./PlanConnectionAlert";
import { CATALOG, catalogEntryFor, mergeMarketplaceApps } from "@/lib/toolCatalog";
import { getAllConnections, subscribeConnections } from "@/lib/connectionsStore";
import { connectTool, getToolConnection, hydrateConnections } from "@/lib/connectService";
import { searchConnectorBrokerApps, testPythonConnection } from "@/lib/auraApi";
import { isVerifiedConnection } from "@/lib/connectionSelection.mjs";
import { hasPlanConnectionGrant, planConnectionRequirements, buildPlanConnectionTools, requirementTools } from "@/lib/planConnections.mjs";
import { planningConnectionsEnabled } from "@/lib/planningFlow.mjs";
import { removeStepInstruction } from "@/lib/planPresentation.mjs";
import { alternativePlanConnection, planConnectionRevision } from "@/lib/planConnectionRoutes.mjs";
import { CONNECTION_CANCELLED } from "@/lib/connectionAttempt.mjs";
const PLAN_REVISION_SCHEMA = {
  type: "object",
  properties: {
    steps: {
      type: "array",
      items: {
        type: "object",
        properties: {
          tool: { type: "string" },
          title: { type: "string" },
          iWill: { type: "string" },
          action: { type: "string" },
          detail: { type: "string" },
          reason: { type: "string" },
          output: { type: "string" },
          flow: {
            type: "array",
            items: {
              type: "object",
              properties: { label: { type: "string" }, value: { type: "string" } },
            },
          },
          riskLevel: { type: "string", enum: ["read", "modify"] },
          riskNote: { type: "string" },
        },
      },
    },
  },
};

const PLAN_HINTS = [
  "Move the email step before the report",
  "Use Gmail instead of Slack",
  "Don't contact leads from the US",
  "Change the whole plan — make it weekly",
];

export default function PlanView({
  plan,
  backendRunId,
  backendPlan,
  onApprove,
  approveLabel = "Start",
  requiredReconnectTools = [],
  onConnectionRecovered,
  onSkipTool,
  onReplaceTool,
  omittedTools = [],
  onRevisePlan,
  onRetryPlan,
  busy = false,
}) {
  const [readinessPassed, setReadinessPassed] = useState(false);
  const [steps, setSteps] = useState(plan.steps);
  const [forceEditIndex, setForceEditIndex] = useState(null);
  const [name, setName] = useState(plan.workflowName || "");
  useEffect(() => {
    setSteps(plan.steps || []);
    setName(plan.workflowName || "");
  }, [plan.steps, plan.workflowName]);
  const [connections, setConnections] = useState(getAllConnections);
  const [connectionsReady, setConnectionsReady] = useState(false);
  useEffect(() => {
    const unsubscribe = subscribeConnections(setConnections);
    hydrateConnections({ force: true })
      .then(() => setConnectionsReady(true))
      .catch(() => setConnectionsReady(false));
    return () => { unsubscribe(); };
  }, []);
  const [connectingTool, setConnectingTool] = useState(null);
  const [connectionProgress, setConnectionProgress] = useState(null);
  const connectionAttemptRef = useRef(null);
  useEffect(() => () => connectionAttemptRef.current?.abort(new Error(CONNECTION_CANCELLED)), []);
  const [connectionErrors, setConnectionErrors] = useState({});
  const hasRequiredGrant = hasPlanConnectionGrant;
  const checkingRef = useRef(false);
  const connectingRef = useRef(false);
  const handleConnect = async (tool) => {
    const controller = new AbortController();
    connectionAttemptRef.current = controller;
    setConnectingTool(tool.name);
    setConnectionProgress({ phase: "preparing" });
    setConnectionErrors((prev) => ({ ...prev, [tool.key]: "" }));
    try {
      const res = await connectTool(tool.name, {
        provider: tool.provider, signal: controller.signal,
        onProgress: (progress) => {
          if (!controller.signal.aborted && connectionAttemptRef.current === controller) setConnectionProgress(progress);
        },
      });
      return res;
    } catch (e) {
      setConnectionErrors((prev) => ({
        ...prev,
        [tool.key]: e?.message || `AURA couldn't connect ${tool.name}. Your plan is unchanged.`,
      }));
    } finally {
      if (connectionAttemptRef.current === controller) {
        connectionAttemptRef.current = null;
        setConnectingTool(null);
        setConnectionProgress(null);
      }
    }
  };

  const handleConnectAll = async () => {
    if (connectingRef.current) return;
    const reusable = needed.find((tool) => connectedAlternatives[tool.key]);
    if (reusable) return handleSwitchConnection(reusable);
    connectingRef.current = true;
    const recovered = [];
    const authorized = new Map();
    try {
      for (const tool of needed) {
        const route = tool.provider || tool.key;
        const result = authorized.get(route) || await handleConnect(tool);
        if (result?.connected) authorized.set(route, result);
        if (!result?.connected) return;
        if (!hasRequiredGrant(tool, result.connection)) {
          setConnectionErrors((previous) => ({ ...previous, [tool.key]:
            "This account does not yet grant the access needed to verify this action. Reconnect with the requested permissions." }));
          return;
        }
        recovered.push({
          name: tool.name,
          connectionId: result.connection?.id || result.tool?.id || null,
        });
      }
      if (recovered.length === needed.length && recovered.every((item) => item.connectionId)) {
        await onConnectionRecovered?.(recovered);
      }
    } finally {
      connectingRef.current = false;
    }
  };


  // Distinct external integrations the plan touches, with the reason each is needed.
  const planTools = useMemo(() => buildPlanConnectionTools(steps, plan),
    [steps, plan.connectionChecklist, plan.connectionRequirements]);
  const [, refreshConnectionRoutes] = useState(0);
  const connectionRouteLookup = connectionsReady && onRevisePlan
    ? [...new Set(planTools.filter((tool) => ["google", "google-workspace"].includes(tool.provider)
      && ["Google Sheets", "Google Docs"].includes(tool.name)).map((tool) => tool.name))].sort().join("|")
    : "";
  useEffect(() => {
    if (!connectionRouteLookup) return undefined;
    let active = true;
    // The broad catalog can omit app-specific route details. Load the same
    // verified app entry used by marketplace search, without starting consent.
    Promise.allSettled(connectionRouteLookup.split("|").map(async (name) => {
      if (alternativePlanConnection({ name, provider: "google" }, CATALOG)) return null;
      return searchConnectorBrokerApps(name);
    })).then((results) => {
      if (!active) return;
      let changed = false;
      for (const result of results) {
        if (result.status === "fulfilled" && result.value?.apps?.length) {
          mergeMarketplaceApps(result.value.apps);
          changed = true;
        }
      }
      if (changed) refreshConnectionRoutes((value) => value + 1);
    });
    return () => { active = false; };
  }, [connectionRouteLookup]);

  const [connectedAlternatives, setConnectedAlternatives] = useState({});
  const alternativesLookup = connectionsReady && onRevisePlan ? JSON.stringify(planTools.flatMap((tool) => {
    const provider = alternativePlanConnection(tool, CATALOG);
    return provider ? [{ key: tool.key, name: tool.name, provider }] : [];
  })) : "[]";
  useEffect(() => {
    let active = true;
    setConnectedAlternatives({});
    Promise.allSettled(JSON.parse(alternativesLookup).map(async (tool) => {
      const account = await getToolConnection(tool.name, null, tool.provider, { exactProvider: true });
      if (!account?.id || !account.enabled || !account.allowed_operations?.length) return null;
      if (!isVerifiedConnection(await testPythonConnection(account.id))) return null;
      return tool.key;
    })).then((results) => {
      if (active) setConnectedAlternatives(Object.fromEntries(results
        .filter((result) => result.status === "fulfilled" && result.value)
        .map((result) => [result.value, true])));
    });
    return () => { active = false; };
  }, [alternativesLookup]);

  // AURA handles connector discovery and setup. The only thing a user may need
  // to do is grant the provider's required account permission.
  // Never claim a connection is missing until the authoritative registry has
  // loaded. Unknown state is not the same thing as disconnected.
  const effectiveConnections = useMemo(() => {
    const next = { ...connections };
    planTools.forEach((tool) => { next[tool.key] = Boolean(connections[tool.name]); });
    requiredReconnectTools.forEach((toolName) => {
      planTools.filter((tool) => tool.name === toolName).forEach((tool) => { next[tool.key] = false; });
    });
    planConnectionRequirements(plan).forEach((requirement) => {
      requirementTools(requirement, steps).forEach((tool) => { next[tool.key] = false; });
    });
    return next;
  }, [connections, requiredReconnectTools, plan.connectionChecklist, plan.connectionRequirements, planTools]);

  const missingTools = connectionsReady
    ? planTools.filter((tool) => !effectiveConnections[tool.key])
    : [];
  const needed = missingTools.filter((tool) => catalogEntryFor(tool.name));
  const backstageOnly = missingTools.filter((tool) => !catalogEntryFor(tool.name));
  const connectionOnly = steps.length === 0 && (plan.connectionRequirements || []).length > 0;
  const connectionCount = needed.length || planTools.length;
  const planningFailure = steps.length === 0 && Boolean(plan.error) && !connectionOnly;
  const connectionsCanOpen = planningConnectionsEnabled(plan.compileState);

  const handleSwitchConnection = async (tool) => {
    const provider = alternativePlanConnection(tool, CATALOG);
    if (!provider || !onRevisePlan || connectingRef.current) return;
    connectingRef.current = true;
    setConnectingTool(tool.name);
    setConnectionProgress({ phase: "replanning" });
    setConnectionErrors((previous) => ({ ...previous, [tool.key]: "" }));
    try {
      const revision = planConnectionRevision(tool, provider, plan.connectionRoutes);
      const result = await onRevisePlan(revision.instruction, { connectionRoutes: revision.connectionRoutes });
      if (result?.ok === false) throw new Error(result.error || "AURA couldn't revise this plan.");
    } catch (error) {
      setConnectionErrors((previous) => ({ ...previous, [tool.key]: error.message }));
    } finally {
      connectingRef.current = false;
      setConnectingTool(null);
      setConnectionProgress(null);
    }
  };

  const handleRecheck = useCallback(async (targetKey = "", silent = false) => {
    if (busy || !connectionsReady || !needed.length || checkingRef.current || connectingRef.current) return;
    checkingRef.current = true;
    if (!silent) setConnectingTool(needed.find((tool) => tool.key === targetKey)?.name || "accounts");
    try {
      const recovered = [];
      for (const tool of needed.filter((item) => !targetKey || item.key === targetKey)) {
        const account = await getToolConnection(tool.name, null, tool.provider, {
          exactProvider: Boolean(tool.provider),
        });
        if (!account?.id || !hasRequiredGrant(tool, account)
          || !isVerifiedConnection(await testPythonConnection(account.id))) continue;
        recovered.push({ name: tool.name, connectionId: account.id });
      }
      if (recovered.length) {
        // Only refresh the full account catalog after a required connection
        // changes. Background checks otherwise re-tested every healthy app
        // every five seconds while the plan remained open.
        await hydrateConnections({ force: true });
        await onConnectionRecovered?.(recovered);
      } else if (targetKey && !silent) setConnectionErrors((previous) => ({
        ...previous, [targetKey]: "This plan needs access through its selected connector. Use Connect or update access, then check again.",
      }));
    } catch (error) {
      if (targetKey && !silent) setConnectionErrors((previous) => ({
        ...previous, [targetKey]: error?.message || "AURA couldn't verify this connection yet.",
      }));
    } finally {
      checkingRef.current = false;
      if (!silent) setConnectingTool(null);
    }
  }, [busy, connectionsReady, needed, onConnectionRecovered]);

  useEffect(() => {
    if (busy || !connectionsReady || !needed.length || !connectionsCanOpen) return undefined;
    // Consent may finish in another tab, browser or device. The plan checks
    // verified backend state while visible; it never infers consent from the
    // popup closing and never starts an external action automatically.
    const onFocus = () => { if (document.visibilityState === "visible") void handleRecheck("", true); };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    const timer = window.setInterval(onFocus, 5000);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [busy, connectionsReady, needed.length, connectionsCanOpen, handleRecheck]);

  const onDragEnd = (res) => {
    if (!res.destination || res.source.index === res.destination.index) return;
    if (onRevisePlan) {
      const moved = steps[res.source.index];
      const destination = steps[res.destination.index];
      const direction = res.destination.index < res.source.index ? "before" : "after";
      onRevisePlan(
        `Move “${moved?.title || moved?.action || `step ${res.source.index + 1}`}” ${direction} “${destination?.title || destination?.action || `step ${res.destination.index + 1}`}”.`
      );
      return;
    }
    setSteps((prev) => {
      const next = [...prev];
      const [moved] = next.splice(res.source.index, 1);
      next.splice(res.destination.index, 0, moved);
      return next;
    });
  };

  const updateStep = (i, updated) => setSteps((prev) => prev.map((s, idx) => (idx === i ? updated : s)));
  const deleteStep = (i) => {
    if (onRevisePlan) {
      const target = steps[i];
      onRevisePlan(removeStepInstruction(target, i));
      return;
    }
    setSteps((prev) => prev.filter((_, idx) => idx !== i));
  };
  const addStep = () => {
    if (onRevisePlan) {
      setPlanInstruction("Add a step that ");
      setPlanEditing(true);
      return;
    }
    setSteps((prev) => [
      ...prev,
      {
        tool: "AURA Intelligence",
        title: "New step",
        iWill: "describe what this step should do",
        action: "Describe what this step should do",
        detail: "",
        reason: "",
        output: "",
        flow: [{ label: "From", value: "—" }],
        riskLevel: "read",
        riskNote: "",
      },
    ]);
  };

  // Tell AURA — natural-language plan-wide edits (reorder, swap tools, scope, restructure)
  const [planInstruction, setPlanInstruction] = useState("");
  const [planSubmitting, setPlanSubmitting] = useState(false);
  const [planError, setPlanError] = useState("");
  const [planEditing, setPlanEditing] = useState(false);

  const submitPlanChange = async () => {
    const text = planInstruction.trim();
    if (!text) return;
    setPlanSubmitting(true);
    setPlanError("");
    try {
      if (onRevisePlan) {
        const result = await onRevisePlan(text);
        if (result?.ok === false) throw new Error(result.error || "AURA couldn't revise this plan.");
        setPlanInstruction("");
        setPlanEditing(false);
        return;
      }
      const res = await aura.integrations.Core.InvokeLLM({
        prompt: `You are AURA, an AI workflow automation platform. Revise the ENTIRE workflow plan based on the user's instruction.

Confirmed intent: "${plan.interpretation || ""}"

Current plan steps:
${JSON.stringify(steps, null, 2)}

User's instruction: "${text}"

Return the FULL revised steps array reflecting the change (reorder, swap tools, add or remove steps, change scope — whatever the instruction asks). Keep every step's structure:
- "title": a short 2-4 word imperative.
- "iWill": what AURA will do, lowercase, no "I'll" prefix.
- "action": plain business-language description.
- "flow": 1-2 entries. Each has "label" (ONLY "Uses" or "Creates") and "value". "Uses" = the tool/data this step reads; "Creates" = the result or destination it produces.
- "riskLevel": "read" or "modify".
- "riskNote": for modify steps, say Start runs the action and the user reviews its completed result. Empty for read.
Preserve unchanged steps exactly. Only modify what the instruction requires.`,
        response_json_schema: PLAN_REVISION_SCHEMA,
      });
      if (res.steps && Array.isArray(res.steps) && res.steps.length) {
        setSteps(res.steps);
        setPlanInstruction("");
        setPlanEditing(false);
      } else {
        setPlanError("Couldn't revise the plan — try rephrasing.");
      }
    } catch (e) {
      setPlanError(e?.message || "Couldn't revise the plan — try rephrasing.");
    } finally {
      setPlanSubmitting(false);
    }
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full max-w-5xl mx-auto">
      {/* Header */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mb-6">
        <div className="flex items-center gap-2 mb-1.5">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <Brain className="w-4 h-4 text-primary" />
          </div>
          <h2 className="text-lg font-semibold">
            {connectionOnly
              ? backstageOnly.length
                ? "AURA is keeping connector setup backstage"
                : connectionCount === 1
                  ? "Connect one account so AURA can finish the plan"
                  : `Connect ${connectionCount} accounts so AURA can finish the plan`
              : planningFailure
                ? "Aura couldn't finish this plan yet"
                : "Here's how Aura plans to complete your task"}
          </h2>
        </div>
        <p className="text-xs text-muted-foreground ml-9 leading-relaxed">
          {connectionOnly
            ? backstageOnly.length
              ? "Your task is saved. AURA will not ask you for API keys, MCP URLs, or technical configuration."
              : connectionCount === 1
                ? "Your task is saved. Planning resumes automatically after the connection is verified."
                : "Your task is saved. Planning resumes automatically after every required connection is verified."
            : planningFailure
              ? "Nothing was executed. Retry planning when you're ready."
            : "Review the steps and change anything that doesn't look right."}
        </p>
      </motion.div>

      {omittedTools.length > 0 && (
        <div className="mb-4 rounded-xl border border-amber-400/25 bg-amber-400/5 p-3 text-xs text-amber-100">
          This plan leaves out {omittedTools.join(", ")} and its dependent steps.
          Review the updated plan before starting it.
        </div>
      )}

      {plan.compileState === "blocked" && !plan.error && (
        <div className="mb-4 rounded-xl border border-amber-400/25 bg-amber-400/5 p-3 text-sm text-amber-100">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4 text-amber-400" />
            <span>AURA couldn't finalize one execution detail</span>
          </div>
          {plan.compileError && (
            <p className="mt-1 text-[11px] leading-relaxed text-amber-100/70">{plan.compileError}</p>
          )}
          {onRetryPlan && (
            <button
              type="button"
              onClick={onRetryPlan}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-amber-300/20 bg-amber-300/5 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-300/10"
            >
              <RotateCcw className="h-3.5 w-3.5" /> Try again
            </button>
          )}
        </div>
      )}

      {plan.error && !connectionOnly && (
        <div className="mb-4 rounded-xl border border-red-400/25 bg-red-400/5 p-3 text-sm text-red-200">
          <p className="font-medium">AURA couldn't build this plan</p>
          <p className="mt-1 text-xs text-red-200/80">{plan.error}</p>
          <p className="mt-1 text-[11px] text-muted-foreground">No external action was started, and your connections are unchanged.</p>
          {onRetryPlan && (
            <button
              type="button"
              onClick={onRetryPlan}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-red-300/20 bg-red-300/5 px-3 py-1.5 text-xs font-medium text-red-100 hover:bg-red-300/10"
            >
              <RotateCcw className="h-3.5 w-3.5" /> Retry planning
            </button>
          )}
        </div>
      )}

      {plan.startError && !connectionOnly && (
        <div className="mb-4 rounded-xl border border-amber-400/25 bg-amber-400/5 p-3 text-sm text-amber-100">
          <p className="font-medium">AURA couldn't start this plan</p>
          <p className="mt-1 text-xs text-amber-100/80">{plan.startError}</p>
          <p className="mt-1 text-[11px] text-muted-foreground">Nothing was executed. The plan remains here so you can review it and press Start again.</p>
        </div>
      )}

      <PlanConnectionAlert
        tools={planTools.filter((tool) => catalogEntryFor(tool.name)).map((tool) => ({
          ...tool, alternativeProvider: onRevisePlan ? alternativePlanConnection(tool, CATALOG) : null,
          alternativeConnected: Boolean(connectedAlternatives[tool.key]),
        }))}
        connections={effectiveConnections}
        connectingTool={connectingTool}
        progress={connectionProgress}
        onCancel={() => connectionAttemptRef.current?.abort(new Error(CONNECTION_CANCELLED))}
        errors={connectionErrors}
        onConnectAll={handleConnectAll}
        onRecheck={handleRecheck}
        onSkipTool={onSkipTool}
        onReplaceTool={onReplaceTool}
        onSwitchConnection={handleSwitchConnection}
        replacements={CATALOG.filter((entry) => connections[entry.name]).map((entry) => entry.name)}
        connectionEnabled={connectionsCanOpen}
      />

      {backstageOnly.length > 0 && (
        <div className="mb-4 rounded-xl border border-amber-400/20 bg-amber-400/5 p-4 text-sm text-amber-100">
          <p className="font-medium">AURA-managed connection required</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {backstageOnly.map((tool) => tool.name).join(", ")} is not yet available through AURA's
            verified one-click connection path. No technical setup is required from you, and nothing
            has been executed.
          </p>
        </div>
      )}

      {connectionOnly && (
        <div className="rounded-xl border border-white/8 bg-card/50 p-4 text-sm text-muted-foreground">
          {backstageOnly.length
            ? "AURA has preserved this task without exposing connector internals. Retry planning after the managed connector is available."
            : "AURA has not executed anything. Connect the requested provider above, or retry planning after updating your connections."}
          {onRetryPlan && (
            <button
              type="button"
              onClick={onRetryPlan}
              className="mt-3 flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-white/5"
            >
              <RotateCcw className="h-3.5 w-3.5" /> Retry planning
            </button>
          )}
        </div>
      )}

      {!busy && plan.compileState !== "blocked" && plan.appliedRevision && <div role="status" className="mb-4 rounded-xl border border-emerald-400/20 bg-emerald-400/5 p-4 text-sm">
        <p className="font-medium text-emerald-300">Plan updated</p>
        <p className="mt-1 text-muted-foreground">{plan.appliedRevision}</p>
      </div>}

      {!connectionOnly && !planningFailure && <>

      {/* Steps */}
      <DragDropContext onDragEnd={onDragEnd}>
        <Droppable droppableId="plan-steps">
          {(provided) => (
            <div {...provided.droppableProps} ref={provided.innerRef} className="mb-2">
              {steps.map((step, i) => (
                <Draggable key={step.key || i} draggableId={`step-${i}`} index={i} isDragDisabled={busy}>
                  {(p) => (
                    <PlanStep
                      step={step}
                      index={i}
                      isLast={i === steps.length - 1}
                      provided={p}
                      onChange={(updated) => updateStep(i, updated)}
                      onDelete={() => deleteStep(i)}
                      onRequestChange={onRevisePlan
                        ? (instruction) => onRevisePlan(
                          `For step ${i + 1}${step.key ? ` (${step.key})` : ""}, “${step.title || step.action || "this step"}”: ${instruction}`
                        )
                        : undefined}
                      forceEdit={forceEditIndex === i}
                      onEditConsumed={() => setForceEditIndex(null)}
                    />
                  )}
                </Draggable>
              ))}
              {provided.placeholder}
            </div>
          )}
        </Droppable>
      </DragDropContext>

      {/* Add step */}
      <button
        onClick={addStep}
        className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl border border-dashed border-white/10 text-xs text-muted-foreground hover:text-foreground hover:border-primary/30 transition-all"
      >
        <Plus className="w-3.5 h-3.5" />
        Add a step
      </button>

      {/* Tell AURA — plan-wide natural-language edit */}
      <div className="mt-3 p-3 rounded-xl border border-primary/15 bg-primary/5">
        <div className="flex items-center gap-2 mb-2">
          <Sparkles className="w-3.5 h-3.5 text-primary" />
          <span className="text-xs font-medium text-primary/90">Tell AURA what to change</span>
          <span className="text-[10px] text-muted-foreground/70">reorder, swap tools, change scope</span>
        </div>
        <AnimatePresence mode="wait">
          {!planEditing ? (
            <motion.button
              key="open"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setPlanEditing(true)}
              className="w-full text-left text-xs text-muted-foreground hover:text-foreground px-3 py-2 rounded-lg border border-dashed border-white/10 hover:border-primary/30 transition-all"
            >
              e.g. “Move the email step before the report” or “Change the whole plan”
            </motion.button>
          ) : (
            <motion.div
              key="edit"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="space-y-2"
            >
              <textarea
                value={planInstruction}
                onChange={(e) => setPlanInstruction(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submitPlanChange();
                  }
                }}
                autoFocus
                rows={2}
                placeholder="Tell AURA what should be different about the plan…"
                className="w-full bg-card/70 border border-primary/20 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 resize-none placeholder:text-muted-foreground/40"
              />
              <div className="flex flex-wrap gap-1.5">
                {PLAN_HINTS.map((h) => (
                  <button
                    key={h}
                    type="button"
                    onClick={() => setPlanInstruction(h)}
                    className="text-[10px] px-2 py-0.5 rounded-full bg-secondary/60 border border-white/8 text-muted-foreground hover:bg-primary/10 hover:border-primary/25 hover:text-foreground transition-all"
                  >
                    {h}
                  </button>
                ))}
              </div>
              {planError && <p className="text-[11px] text-red-400">{planError}</p>}
              <div className="flex items-center gap-2">
                <button
                  onClick={submitPlanChange}
                  disabled={planSubmitting || !planInstruction.trim()}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {planSubmitting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                  {planSubmitting ? "Revising…" : "Revise plan"}
                </button>
                <button
                  onClick={() => {
                    setPlanEditing(false);
                    setPlanInstruction("");
                    setPlanError("");
                  }}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-white/10 text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
                >
                  <X className="w-3.5 h-3.5" /> Cancel
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {backendRunId && !plan.provisional && plan.compileState !== "waiting_for_connection" && !plan.error && <RunReadiness runId={backendRunId} plan={plan} backendPlan={backendPlan} steps={steps} onReady={setReadinessPassed} />}
      <RunSupportAccess runId={backendRunId} />
      {/* Bottom approval bar */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mt-5 p-4 rounded-xl border border-white/6 bg-card/50"
      >
        <h3 className="text-sm font-semibold mb-1">
          {plan.compileState === "blocked" || plan.error ? "Plan needs another try" : "Ready to start?"}
        </h3>
        <p className="text-xs text-muted-foreground leading-relaxed mb-3">
          {plan.compileState === "blocked" || plan.error
            ? "Nothing has started. Try again to finish preparing this plan."
            : plan.compileState === "validating"
              ? "You can start now. AURA will prepare the actions while you follow its progress."
            : "Aura will follow this plan and handle technical preparation during execution."}
        </p>
        <div className="mb-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name this workflow (optional) — e.g. Weekly prospecting"
            className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40"
          />
        </div>
        <div className="flex items-center justify-end gap-3">
          {backendRunId && <p className="max-w-sm text-right text-xs text-muted-foreground">Start runs the reviewed plan. Review each tool’s result and edit it if needed.</p>}
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => {
              if (plan.compileState === "waiting_for_connection"
                || (!plan.provisional && missingTools.length > 0)) {
                void handleConnectAll();
                return;
              }
              onApprove(steps, name.trim());
            }}
            disabled={(steps.length === 0 && plan.compileState !== "blocked") || (Boolean(backendRunId) && !plan.provisional && plan.compileState !== "waiting_for_connection" && !plan.error && missingTools.length === 0 && !readinessPassed)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700 text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {plan.compileState === "blocked" || plan.error ? "Try again"
              : plan.compileState === "waiting_for_connection" || (!plan.provisional && missingTools.length > 0)
                ? "Connect to start" : approveLabel} <ArrowRight className="w-4 h-4" />
          </motion.button>
        </div>
      </motion.div>
      </>}
    </motion.div>
  );
}
