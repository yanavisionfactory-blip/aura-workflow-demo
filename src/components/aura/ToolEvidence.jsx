import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, AlertTriangle, ChevronDown, Clock } from "lucide-react";
import { toolEvidence } from "@/lib/toolEvidence.mjs";

const labels = { completed: "Completed", failed: "Failed", blocked: "Blocked", provider_error: "Provider error", running: "Running", recovering: "Checking response", pending: "Not run", skipped: "Skipped", awaiting_approval: "Awaiting review" };

export function EvidenceValue({ value, level = 0 }) {
  const [shown, setShown] = useState(20);
  if (value === null || value === undefined) return <span className="text-muted-foreground">No value returned</span>;
  if (typeof value !== "object") return <span className="whitespace-pre-wrap break-words">{String(value)}</span>;
  if (Array.isArray(value)) {
    if (!value.length) return <p className="text-muted-foreground">Empty list returned (0 rows)</p>;
    const tabular = value.every((item) => item && typeof item === "object" && !Array.isArray(item));
    const columns = tabular ? [...new Set(value.flatMap(Object.keys))] : [];
    const flat = columns.length > 0 && columns.length <= 12 && value.every((item) => Object.values(item).every((field) => field === null || typeof field !== "object"));
    return <div className="space-y-3">
      <p className="text-xs text-muted-foreground">{value.length.toLocaleString()} rows · showing {Math.min(shown, value.length)}</p>
      {flat ? <div className="max-h-[32rem] overflow-auto rounded-xl border border-white/10"><table className="w-full text-left text-xs"><thead className="sticky top-0 bg-[#172238]"><tr>{columns.map((key) => <th key={key} className="whitespace-nowrap px-3 py-2 font-semibold">{key}</th>)}</tr></thead><tbody className="divide-y divide-white/10">{value.slice(0, shown).map((item, index) => <tr key={index}>{columns.map((key) => <td key={key} className="min-w-28 max-w-sm break-words px-3 py-2 align-top">{item[key] === null ? "null" : String(item[key] ?? "")}</td>)}</tr>)}</tbody></table></div>
        : <div className="space-y-2">{value.slice(0, shown).map((item, index) => <details key={index} open={value.length <= 3} className="rounded-lg border border-white/10 p-3"><summary className="cursor-pointer text-xs text-muted-foreground">Row {index + 1}</summary><div className="mt-2"><EvidenceValue value={item} level={level + 1} /></div></details>)}</div>}
      {shown < value.length && <button type="button" onClick={() => setShown((count) => count + 100)} className="rounded-lg border border-primary/30 px-3 py-2 text-xs text-primary">Show next {Math.min(100, value.length - shown)} rows</button>}
    </div>;
  }
  const entries = Object.entries(value);
  if (!entries.length) return <p className="text-muted-foreground">Empty object returned</p>;
  if (level > 8) return <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(value, null, 2)}</pre>;
  return <dl className="space-y-3">{entries.map(([key, item]) => <div key={key} className="min-w-0 border-l border-white/10 pl-3"><dt className="mb-1 text-xs font-semibold text-[#a6c8ef]">{key}</dt><dd className="text-sm leading-6"><EvidenceValue value={item} level={level + 1} /></dd></div>)}</dl>;
}

export default function ToolEvidence({ activity = [], activityRequest = null, initiallyOpen = false }) {
  const records = useMemo(() => toolEvidence(activity), [activity]);
  const tools = [...new Set(records.map((item) => item.tool))];
  const [selected, setSelected] = useState("");
  const activityRef = useRef(null);
  const actionRefs = useRef(new Map());
  useEffect(() => {
    if (!activityRequest) return;
    setSelected("");
    if (activityRef.current) activityRef.current.open = true;
  }, [activityRequest]);
  useEffect(() => {
    if (!activityRequest || selected) return;
    const action = actionRefs.current.get(activityRequest.id);
    if (action) {
      action.open = true;
      action.scrollIntoView({ block: "nearest" });
    }
  }, [activityRequest, selected]);
  if (!records.length) return null;
  const visible = selected && tools.includes(selected) ? records.filter((item) => item.tool === selected) : records;
  return <section aria-label="Results by tool" className="mb-8 rounded-2xl border border-primary/20 bg-card/60 p-5 sm:p-6">
    <h3 className="mb-3 text-sm font-semibold">Tools used</h3>
    <div className="mb-3 flex flex-wrap gap-2">{tools.map((tool) => <span key={tool} className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-muted-foreground">{tool}</span>)}</div>
    <details ref={activityRef} open={initiallyOpen || undefined}>
    <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-medium text-primary [&::-webkit-details-marker]:hidden">View activity<ChevronDown className="h-3 w-3" /></summary>
    <p className="mt-3 text-sm text-muted-foreground">Inspect the inputs, returned data and status of each saved workflow step. A connection alone is not a completed tool run.</p>
    <div className="my-4 flex flex-wrap gap-2" role="group" aria-label="Filter tool results">{["", ...tools].map((tool) => <button key={tool} type="button" aria-pressed={selected === tool} onClick={() => setSelected(tool)} className={`rounded-full border px-3 py-1.5 text-xs ${selected === tool ? "border-primary/60 bg-primary/15 text-primary" : "border-white/15 text-muted-foreground"}`}>{tool || "All tools"} ({tool ? records.filter((item) => item.tool === tool).length : records.length})</button>)}</div>
    <div className="space-y-3">{visible.map((item) => <details key={item.id} ref={(element) => {
      if (element) actionRefs.current.set(item.id, element); else actionRefs.current.delete(item.id);
    }} className="group rounded-xl border border-white/10 bg-[#0c1422]">
      <summary className="flex cursor-pointer list-none items-start gap-3 p-4 [&::-webkit-details-marker]:hidden">
        {item.status === "completed" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" /> : ["failed", "blocked", "provider_error"].includes(item.status) ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" /> : <Clock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />}
        <span className="min-w-0 flex-1"><span className="block text-xs font-semibold text-primary">{item.tool}</span><span className="mt-1 block text-sm font-medium">{item.action}</span></span>
        <span className="shrink-0 text-xs text-muted-foreground">{labels[item.status] || item.status}</span><ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground group-open:rotate-180" />
      </summary>
      <div className="space-y-4 border-t border-white/10 p-4">
        {item.operation && <p className="break-all text-xs text-muted-foreground">Operation: {item.operation}</p>}
        {(item.startedAt || item.completedAt) && <p className="text-xs text-muted-foreground">{item.startedAt && `Started ${item.startedAt}`}{item.completedAt && ` · Finished ${item.completedAt}`}</p>}
        {item.error && <p role="status" className="whitespace-pre-wrap break-words rounded-lg bg-amber-400/10 p-3 text-sm text-amber-200">{typeof item.error === "string" ? item.error : JSON.stringify(item.error)}</p>}
        <details className="rounded-lg border border-white/10 p-3"><summary className="cursor-pointer text-xs font-semibold">Inputs used</summary><div className="mt-3"><EvidenceValue value={item.inputs} /></div></details>
        <div><h4 className="mb-3 text-sm font-semibold">Returned data</h4>{item.hasResponse ? <EvidenceValue value={item.response} /> : <p className="text-sm text-muted-foreground">No provider response is saved for this step. This does not mean the provider returned zero results.</p>}</div>
      </div>
    </details>)}</div>
    </details>
  </section>;
}
