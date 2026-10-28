import { useState } from "react";
import { toolResultName } from "@/lib/toolResultViews.mjs";
import ToolActionScreen from "./ToolActionScreen";
import ResultRevisionComposer from "./ResultRevisionComposer";

export default function PlanToolWorkspace({ steps = [], onRevise }) {
  const groups = [...new Set(steps.map((step) => toolResultName(step.tool || step.tool_slug, step.operation)))];
  const preferred = groups.includes("Frame.io") ? "Frame.io" : toolResultName(steps.find((step) => step.riskLevel === "modify")?.tool || steps[0]?.tool, steps.find((step) => step.riskLevel === "modify")?.operation || steps[0]?.operation);
  const [selected, setSelected] = useState(preferred);
  const tool = groups.includes(selected) ? selected : groups[0];
  const candidates = steps.filter((step) => toolResultName(step.tool || step.tool_slug, step.operation) === tool);
  const step = candidates.find((item) => item.operation === "frameio.comments.list") || candidates.find((item) => item.riskLevel === "modify") || candidates.at(-1);
  if (!step) return null;
  const args = step.resolvedArguments || step.arguments || {};
  return <section aria-label="Tool workspace preview" className="mb-6 rounded-2xl border border-white/10 bg-[#0c121e]/65 p-4">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><h3 className="text-sm font-semibold">Preview by tool</h3><span className="text-[11px] text-muted-foreground">Planned view · content loads when the steps run</span></div>
    <div role="tablist" aria-label="Preview tools" className="mb-4 flex gap-2 overflow-x-auto">{groups.map((name) => <button type="button" key={name} role="tab" aria-selected={name === tool} onClick={() => setSelected(name)} className={`shrink-0 rounded-lg border px-4 py-2 text-xs font-medium ${name === tool ? "border-violet-400/40 bg-violet-400/10 text-violet-200" : "border-white/10 text-muted-foreground"}`}>{name}</button>)}</div>
    <div role="tabpanel" aria-label={`${tool} planned workspace`}><ToolActionScreen step={{ ...step, tool }} args={typeof args === "object" ? args : {}} /></div>
    <ResultRevisionComposer onSubmit={onRevise ? (instruction) => onRevise(`For the ${tool} workspace: ${instruction}`) : null} label="Change this preview" placeholder="Describe how this tool’s output should change…" hint="AURA revises the plan. Review the changes before starting." />
  </section>;
}
