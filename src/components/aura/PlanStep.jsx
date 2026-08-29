import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, Pencil, X, GripVertical, Shield, Move, Loader2 } from "lucide-react";
import { base44 } from "@/api/base44Client";
import ToolPicker from "./ToolPicker";

const STEP_SCHEMA = {
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
};

const HINTS = [
  { label: "Change the source", prefill: "Change the source to " },
  { label: "Change the result", prefill: "Change the result to " },
  { label: "Add a step", prefill: "Add a step after this one that " },
  { label: "Something else", prefill: "" },
];

// Normalize legacy flow labels down to the two the user sees: Uses / Creates
const LABEL_MAP = {
  From: "Uses",
  Using: "Uses",
  "Sends via": "Uses",
  "Expected result": "Creates",
  Creates: "Creates",
  "Sends to": "Creates",
  To: "Creates",
  "Result goes to": "Creates",
};
const normLabel = (l) => LABEL_MAP[l] || l;

export default function PlanStep({ step, index, isLast, provided, onChange, onDelete, forceEdit, onEditConsumed, connections = {}, onConnect, connectingTool, onConnectRequest }) {
  const [changing, setChanging] = useState(false);
  const [changeText, setChangeText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const title = step.title || step.action;
  const iWill = step.iWill || (step.action ? step.action[0].toLowerCase() + step.action.slice(1) : "");
  const flow = (step.flow || []).map((f) => ({ ...f, label: normLabel(f.label) }));
  const needsApproval = step.riskLevel === "modify";

  useEffect(() => {
    if (forceEdit) {
      setChanging(true);
      onEditConsumed && onEditConsumed();
    }
  }, [forceEdit]);

  const submitChange = async () => {
    const text = changeText.trim();
    if (!text) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await base44.integrations.Core.InvokeLLM({
        prompt: `You are AURA, an AI workflow automation platform. Revise this single workflow step based on the user's requested change.

Current step:
${JSON.stringify(step, null, 2)}

User's change request: "${text}"

Return the REVISED step with all fields updated to reflect the change. Keep the same structure:
- "title": a short 2-4 word imperative.
- "iWill": what AURA will do, lowercase, no "I'll" prefix.
- "action": plain business-language description.
- "flow": 1-2 entries. Each has "label" (ONLY "Uses" or "Creates") and "value". "Uses" = the tool/data this step reads; "Creates" = the result or destination it produces.
- "riskLevel": "read" or "modify".
- "riskNote": for modify steps, a short line saying the user will review it before it happens (e.g. "You'll review the emails before they're sent."). Empty for read.`,
        response_json_schema: STEP_SCHEMA,
      });
      onChange({ ...step, ...res, riskLevel: res.riskLevel || step.riskLevel });
      setChanging(false);
      setChangeText("");
    } catch (e) {
      setError("Couldn't update that step — please try rephrasing.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div ref={provided.innerRef} {...provided.draggableProps} className="relative">
      {!isLast && (
        <div className="absolute left-5 top-12 bottom-0 w-px bg-gradient-to-b from-primary/20 to-transparent" />
      )}
      <div className="flex gap-4 pb-5">
        {/* Number / drag handle */}
        <div
          {...provided.dragHandleProps}
          title="Drag to reorder"
          className="group/handle relative z-10 flex-shrink-0 w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center cursor-grab active:cursor-grabbing hover:bg-primary/20 transition-colors"
        >
          <GripVertical className="w-4 h-4 text-primary/70 group-hover/handle:hidden transition-colors" />
          <span className="hidden group-hover/handle:flex items-center gap-0.5 text-[9px] font-medium text-primary">
            <Move className="w-3 h-3" /> Move
          </span>
          <span className="absolute -top-1 -right-1 text-[9px] font-mono font-bold text-primary bg-background rounded-full px-1 border border-primary/20 group-hover/handle:opacity-0 transition-opacity">
            {index + 1}
          </span>
        </div>

        {/* Card */}
        <div className="flex-1 min-w-0 rounded-xl border border-white/6 bg-card/50 hover:bg-card/80 transition-colors">
          <div className="p-4">
            {/* Title + Change */}
            <div className="flex items-start justify-between gap-3 mb-1.5">
              <h4 className="text-sm font-semibold leading-snug">{title}</h4>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <button
                  onClick={() => setChanging((c) => !c)}
                  className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-full border border-white/10 text-muted-foreground hover:text-foreground hover:border-white/20 transition-colors"
                >
                  <Pencil className="w-3 h-3" /> Change
                </button>
              </div>
            </div>

            {/* I'll ... */}
            <p className="text-sm text-muted-foreground leading-relaxed mb-3">I'll {iWill}.</p>

            {/* Flow — Uses (editable) / Creates */}
            {flow.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {flow.map((f, i) =>
                  f.label === "Uses" ? (
                    <ToolPicker
                      key={i}
                      value={f.value}
                      connections={connections}
                      connecting={connectingTool === f.value}
                      onConnect={onConnect}
                      onConnectRequest={onConnectRequest}
                      onChange={(newName) => {
                        const newFlow = [...(step.flow || [])];
                        newFlow[i] = { ...newFlow[i], value: newName };
                        onChange({ ...step, flow: newFlow, tool: newName });
                      }}
                    />
                  ) : (
                    <div
                      key={i}
                      className="flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-lg bg-primary/5 border border-primary/10"
                    >
                      <span className="text-primary/50 font-medium">{f.label}:</span>
                      <span className="text-foreground/80">{f.value}</span>
                    </div>
                  )
                )}
              </div>
            )}

            {/* Approval shield for steps that send or change things */}
            {needsApproval && (
              <div className="mt-3 flex items-start gap-1.5 text-[11px] text-amber-300/90">
                <Shield className="w-3.5 h-3.5 flex-shrink-0 mt-px" />
                <span>{step.riskNote || "You'll review this before it happens."}</span>
              </div>
            )}
          </div>

          {/* Change panel */}
          <AnimatePresence>
            {changing && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="border-t border-white/6 overflow-hidden rounded-b-xl"
              >
                <div className="p-4 space-y-3">
                  <div>
                    <p className="text-sm font-medium">What would you like to change?</p>
                    <p className="text-xs text-muted-foreground mt-0.5">Tell Aura what should be different.</p>
                  </div>
                  <textarea
                    value={changeText}
                    onChange={(e) => setChangeText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        submitChange();
                      }
                      if (e.key === "Escape") {
                        setChanging(false);
                        setChangeText("");
                        setError("");
                      }
                    }}
                    autoFocus
                    rows={2}
                    placeholder="For example: 'Use Salesforce instead of HubSpot'"
                    className="w-full bg-card/70 border border-primary/20 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 resize-none"
                  />
                  <div className="flex items-center flex-wrap gap-1.5">
                    <button
                      onClick={() => setChangeText(`Use [tool] instead of ${step.tool}`)}
                      className="text-[10px] px-2 py-0.5 rounded-full border border-primary/20 text-primary/80 hover:text-primary hover:bg-primary/10 transition-colors"
                    >
                      Change the tool
                    </button>
                    {HINTS.map((h) => (
                      <button
                        key={h.label}
                        onClick={() => setChangeText(h.prefill)}
                        className="text-[10px] px-2 py-0.5 rounded-full border border-white/10 text-muted-foreground hover:text-foreground hover:border-primary/20 transition-colors"
                      >
                        {h.label}
                      </button>
                    ))}
                    <button
                      onClick={onDelete}
                      className="text-[10px] px-2 py-0.5 rounded-full border border-red-400/20 text-red-400/70 hover:bg-red-500/10 hover:text-red-400 transition-colors"
                    >
                      Remove this step
                    </button>
                  </div>
                  {error && <p className="text-[11px] text-red-400">{error}</p>}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={submitChange}
                      disabled={submitting || !changeText.trim()}
                      className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                    >
                      {submitting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                      {submitting ? "Updating…" : "Update step"}
                    </button>
                    <button
                      onClick={() => {
                        setChanging(false);
                        setChangeText("");
                        setError("");
                      }}
                      className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-white/10 text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
                    >
                      <X className="w-3 h-3" /> Cancel
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

    </div>
  );
}