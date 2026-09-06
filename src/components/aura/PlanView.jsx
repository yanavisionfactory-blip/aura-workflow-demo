import { useState, useMemo, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import { Brain, Plus, ArrowRight, Sparkles, Loader2, Check, X } from "lucide-react";
import { aura } from "@/api/auraClient";
import PlanStep from "./PlanStep";
import PlanConnectionAlert from "./PlanConnectionAlert";
import { CATALOG } from "@/lib/toolCatalog";
import { getAllConnections, subscribeConnections } from "@/lib/connectionsStore";
import { connectTool, hydrateConnections } from "@/lib/connectService";

// Case-insensitive lookup so LLM tool-name variations ("meta ads", "Jira Software")
// still resolve to the canonical name in the registry — keeps connection detection
// reliable as real tools get integrated.
const TOOL_BY_NAME = Object.fromEntries(
  CATALOG.map((tool) => [tool.name.toLowerCase(), tool.name])
);
const resolveTool = (raw) => {
  if (!raw || typeof raw !== "string") return null;
  const key = raw.trim().toLowerCase();
  if (key === "aura intelligence") return null;
  return TOOL_BY_NAME[key] || null;
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

export default function PlanView({ plan, onApprove, approveLabel = "Start" }) {
  const [steps, setSteps] = useState(plan.steps);
  const [forceEditIndex, setForceEditIndex] = useState(null);
  const [name, setName] = useState(plan.workflowName || "");
  const [connections, setConnections] = useState(getAllConnections);
  useEffect(() => {
    const unsubscribe = subscribeConnections(setConnections);
    hydrateConnections().catch(() => {});
    return () => { unsubscribe(); };
  }, []);
  const [connectingTool, setConnectingTool] = useState(null);
  const [connectionErrors, setConnectionErrors] = useState({});
  const handleConnect = async (name) => {
    setConnectingTool(name);
    setConnectionErrors((prev) => ({ ...prev, [name]: "" }));
    try {
      const res = await connectTool(name);
      if (res.needsConfiguration) {
        setConnectionErrors((prev) => ({
          ...prev,
          [name]: `AURA couldn't finish connecting ${name} automatically. Please try again.`,
        }));
      }
      if (res.connected) await hydrateConnections();
    } catch (e) {
      setConnectionErrors((prev) => ({
        ...prev,
        [name]: e?.message?.includes("AURA kept your plan unchanged")
          ? e.message
          : `AURA couldn't connect ${name}. Your plan is unchanged.`,
      }));
    } finally {
      setConnectingTool(null);
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
    return out;
  }, [steps]);

  // AURA handles connector discovery and setup. The only thing a user may need
  // to do is grant the provider's required account permission.
  const needed = planTools.filter((tool) => !connections[tool.name]);

  const onDragEnd = (res) => {
    if (!res.destination || res.source.index === res.destination.index) return;
    setSteps((prev) => {
      const next = [...prev];
      const [moved] = next.splice(res.source.index, 1);
      next.splice(res.destination.index, 0, moved);
      return next;
    });
  };

  const updateStep = (i, updated) => setSteps((prev) => prev.map((s, idx) => (idx === i ? updated : s)));
  const deleteStep = (i) => setSteps((prev) => prev.filter((_, idx) => idx !== i));
  const addStep = () =>
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
      setPlanError("Couldn't revise the plan — try rephrasing.");
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
          <h2 className="text-lg font-semibold">Here's how Aura plans to complete your task</h2>
        </div>
        <p className="text-xs text-muted-foreground ml-9 leading-relaxed">
          Review the steps and change anything that doesn't look right.
        </p>
      </motion.div>

      {plan.error && (
        <div className="mb-4 rounded-xl border border-red-400/25 bg-red-400/5 p-3 text-sm text-red-200">
          <p className="font-medium">AURA couldn't build this plan</p>
          <p className="mt-1 text-xs text-red-200/80">{plan.error}</p>
        </div>
      )}

      <PlanConnectionAlert
        tools={needed}
        connections={connections}
        connectingTool={connectingTool}
        errors={connectionErrors}
        onConnect={handleConnect}
      />

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
        <h3 className="text-sm font-semibold mb-1">Ready to start?</h3>
        <p className="text-xs text-muted-foreground leading-relaxed mb-3">
          Aura will follow this plan and ask for your approval before sending or changing anything important.
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
          {needed.length > 0 && (
            <span className="mr-auto text-xs text-amber-300">
              Connect {needed.map((tool) => tool.name).join(", ")} to start
            </span>
          )}
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => onApprove(steps, name.trim())}
            disabled={needed.length > 0 || steps.length === 0 || Boolean(plan.error)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700 text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {approveLabel} <ArrowRight className="w-4 h-4" />
          </motion.button>
        </div>
      </motion.div>
    </motion.div>
  );
}
