import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import { AlertTriangle, Brain, Plus, ArrowRight, Sparkles, Loader2, Check, X, RotateCcw } from "lucide-react";
import { aura } from "@/api/auraClient";
import PlanStep from "./PlanStep";
import PlanConnectionAlert from "./PlanConnectionAlert";
import { CATALOG, catalogEntryFor } from "@/lib/toolCatalog";
import { getAllConnections, subscribeConnections } from "@/lib/connectionsStore";
import { connectTool, getToolConnection, hydrateConnections } from "@/lib/connectService";
import { testPythonConnection } from "@/lib/auraApi";
import { isVerifiedConnection } from "@/lib/connectionSelection.mjs";
import { planningConnectionsEnabled } from "@/lib/planningFlow.mjs";
const resolveTool = (raw) => {
  if (!raw || typeof raw !== "string") return null;
  const key = raw.trim().toLowerCase();
  if (key === "aura intelligence") return null;
  return catalogEntryFor(key)?.name || null;
};

const slugifyTool = (value) => String(value || "")
  .trim()
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, "-")
  .replace(/^-|-$/g, "");

const REQUIREMENT_ALIASES = {
  google: "Google Drive",
  "google-workspace": "Google Drive",
  atlassian: "Jira",
  jira: "Jira",
};

const resolveRequirementTool = (raw, permissions = []) => {
  const value = String(raw || "").trim();
  if (["google", "google-workspace"].includes(slugifyTool(value))) {
    if (permissions.some((operation) => operation.startsWith("gmail."))) return "Gmail";
    if (permissions.some((operation) => operation.startsWith("calendar."))) return "Google Calendar";
    if (permissions.some((operation) => operation.startsWith("docs."))) return "Google Docs";
  }
  const catalogMatch = catalogEntryFor(value);
  if (catalogMatch) return catalogMatch.name;
  const slug = slugifyTool(value);
  if (REQUIREMENT_ALIASES[slug]) return REQUIREMENT_ALIASES[slug];
  const exact = CATALOG.find(
    (tool) => slugifyTool(tool.name) === slug || tool.name.toLowerCase() === value.toLowerCase()
  );
  if (exact) return exact.name;
  const contained = CATALOG.find((tool) => value.toLowerCase().includes(tool.name.toLowerCase()));
  return contained?.name || value;
};

const toolsForStep = (step) => {
  const names = [step.tool, ...(step.flow || []).filter((item) => item.label === "Uses").map((item) => item.value)]
    .map(resolveTool)
    .filter(Boolean);
  return [...new Set(names)];
};

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
  onApprove,
  approveLabel = "Start",
  requiredReconnectTools = [],
  onConnectionRecovered,
  onSkipTool,
  onReplaceTool,
  omittedTools = [],
  onRevisePlan,
  onRetryPlan,
}) {
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
  const [connectionErrors, setConnectionErrors] = useState({});
  const hasRequiredGrant = useCallback((tool, account) => (plan.connectionChecklist || [])
    .filter((requirement) => requirement.status !== "satisfied"
      && String(requirement.reason || "").startsWith("Authorize exact operations")
      && resolveRequirementTool(requirement.provider_hint || requirement.capability,
        requirement.required_permissions) === tool.name)
    .every((requirement) => (requirement.required_permissions || [])
      .every((operation) => (account?.allowed_operations || []).includes(operation))), [plan.connectionChecklist]);
  const checkingRef = useRef(false);
  const connectingRef = useRef(false);
  const handleConnect = async (name, provider = null) => {
    setConnectingTool(name);
    setConnectionErrors((prev) => ({ ...prev, [name]: "" }));
    try {
      const res = await connectTool(name, { provider });
      if (res.connected) {
        await hydrateConnections({ force: true });
      }
      return res;
    } catch (e) {
      setConnectionErrors((prev) => ({
        ...prev,
        [name]: e?.message || `AURA couldn't connect ${name}. Your plan is unchanged.`,
      }));
    } finally {
      setConnectingTool(null);
    }
  };

  const handleConnectAll = async () => {
    connectingRef.current = true;
    const recovered = [];
    try {
      for (const tool of needed) {
        const result = await handleConnect(tool.name, tool.provider);
        if (!result?.connected) return;
        if (!hasRequiredGrant(tool, result.connection)) {
          setConnectionErrors((previous) => ({ ...previous, [tool.name]:
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
  const planTools = useMemo(() => {
    const seen = new Set();
    const out = [];
    steps.forEach((s) => {
      toolsForStep(s).forEach((t) => {
        if (!t || seen.has(t)) return;
        seen.add(t);
        const match = steps.find(
          (st) =>
            resolveTool(st.tool) === t ||
            (st.flow || []).some((f) => f.label === "Uses" && resolveTool(f.value) === t)
        );
        out.push({ name: t, reason: match ? match.iWill || match.action || "" : "" });
      });
    });
    const requirements = plan.connectionChecklist?.length
      ? plan.connectionChecklist.filter((requirement) => requirement.status !== "satisfied")
      : (plan.connectionRequirements || []);
    requirements.forEach((requirement) => {
      const raw = typeof requirement === "string"
        ? requirement
        : requirement.canonical_provider || requirement.provider_hint || requirement.capability;
      const name = resolveRequirementTool(raw, requirement.required_permissions);
      if (!name) return;
      if (seen.has(name)) {
        if (String(raw).toLowerCase().endsWith("-mcp")) {
          const existing = out.find((item) => item.name === name);
          if (existing) existing.provider = raw;
        }
        return;
      }
      seen.add(name);
      out.push({
        name,
        provider: raw,
        reason: typeof requirement === "object" && requirement.reason
          ? requirement.reason
          : `AURA needs ${name} access to finish building this plan`,
      });
    });
    return out;
  }, [steps, plan.connectionChecklist, plan.connectionRequirements]);

  // AURA handles connector discovery and setup. The only thing a user may need
  // to do is grant the provider's required account permission.
  // Never claim a connection is missing until the authoritative registry has
  // loaded. Unknown state is not the same thing as disconnected.
  const effectiveConnections = useMemo(() => {
    const next = { ...connections };
    requiredReconnectTools.forEach((toolName) => { next[toolName] = false; });
    const authoritativeRequirements = plan.connectionChecklist?.length
      ? plan.connectionChecklist.filter((requirement) => requirement.status !== "satisfied")
      : (plan.connectionRequirements || []);
    authoritativeRequirements.forEach((requirement) => {
      const raw = typeof requirement === "string"
        ? requirement
        : requirement.canonical_provider || requirement.provider_hint || requirement.capability;
      const name = resolveRequirementTool(raw, requirement.required_permissions);
      if (name) next[name] = false;
    });
    return next;
  }, [connections, requiredReconnectTools, plan.connectionChecklist, plan.connectionRequirements]);

  const missingTools = connectionsReady
    ? planTools.filter((tool) => !effectiveConnections[tool.name])
    : [];
  const needed = missingTools.filter((tool) => catalogEntryFor(tool.name));
  const backstageOnly = missingTools.filter((tool) => !catalogEntryFor(tool.name));
  const connectionOnly = steps.length === 0 && (plan.connectionRequirements || []).length > 0;
  const connectionCount = needed.length || planTools.length;
  const planningFailure = steps.length === 0 && Boolean(plan.error) && !connectionOnly;
  const connectionsCanOpen = planningConnectionsEnabled(plan.compileState);

  const handleRecheck = useCallback(async (targetName = "", silent = false) => {
    if (!connectionsReady || !needed.length || checkingRef.current || connectingRef.current) return;
    checkingRef.current = true;
    if (!silent) setConnectingTool(targetName || "accounts");
    try {
      const recovered = [];
      for (const tool of needed.filter((item) => !targetName || item.name === targetName)) {
        const account = await getToolConnection(tool.name, null, tool.provider);
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
      } else if (targetName && !silent) setConnectionErrors((previous) => ({
        ...previous, [targetName]: "AURA has not verified this account yet. Finish provider consent, then check again.",
      }));
    } catch (error) {
      if (targetName && !silent) setConnectionErrors((previous) => ({
        ...previous, [targetName]: error?.message || "AURA couldn't verify this connection yet.",
      }));
    } finally {
      checkingRef.current = false;
      if (!silent) setConnectingTool(null);
    }
  }, [connectionsReady, needed, onConnectionRecovered, hasRequiredGrant]);

  useEffect(() => {
    if (!connectionsReady || !needed.length || !connectionsCanOpen) return undefined;
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
  }, [connectionsReady, needed.length, connectionsCanOpen, handleRecheck]);

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
      onRevisePlan(`Remove “${target?.title || target?.action || `step ${i + 1}`}” from the plan.`);
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
- "riskNote": for modify steps, a short line saying the user will review it before it happens. Empty for read.
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
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full max-w-2xl mx-auto">
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
          New plan without {omittedTools.join(", ")}. Any dependent steps and links must be removed.
          Review the revised plan before starting it.
        </div>
      )}

      {plan.compileState === "blocked" && (
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
        tools={planTools.filter((tool) => catalogEntryFor(tool.name))}
        connections={effectiveConnections}
        connectingTool={connectingTool}
        errors={connectionErrors}
        onConnectAll={handleConnectAll}
        onRecheck={handleRecheck}
        onSkipTool={onSkipTool}
        onReplaceTool={onReplaceTool}
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

      {!connectionOnly && !planningFailure && <>

      {/* Steps */}
      <DragDropContext onDragEnd={onDragEnd}>
        <Droppable droppableId="plan-steps">
          {(provided) => (
            <div {...provided.droppableProps} ref={provided.innerRef} className="mb-2">
              {steps.map((step, i) => (
                <Draggable key={i} draggableId={`step-${i}`} index={i}>
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
                          `For “${step.title || step.action || `step ${i + 1}`}”: ${instruction}`
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

      {/* Bottom approval bar */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mt-5 p-4 rounded-xl border border-white/6 bg-card/50"
      >
        <h3 className="text-sm font-semibold mb-1">
          {plan.compileState === "blocked" ? "Plan needs another try"
            : ["starting", "validating"].includes(plan.compileState) ? "Preparing your workflow" : "Ready to start?"}
        </h3>
        <p className="text-xs text-muted-foreground leading-relaxed mb-3">
          {plan.compileState === "blocked"
            ? "Nothing has started. Try again to finish preparing this plan."
            : plan.compileState === "starting"
              ? "AURA is checking the exact steps. Your request to start is saved; you'll review any external changes before they happen."
            : plan.compileState === "validating"
              ? "AURA is preparing the exact actions. You can request a start now; you'll review any external changes before they happen."
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
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => onApprove(steps, name.trim())}
            disabled={Boolean(plan.error) || ["starting", "waiting_for_connection"].includes(plan.compileState) || (!plan.provisional && missingTools.length > 0) || (steps.length === 0 && plan.compileState !== "blocked")}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700 text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {plan.compileState === "blocked" ? "Try again" : plan.compileState === "starting" ? "Preparing…" : approveLabel} <ArrowRight className="w-4 h-4" />
          </motion.button>
        </div>
      </motion.div>
      </>}
    </motion.div>
  );
}
