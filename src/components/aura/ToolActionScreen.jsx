import { useState } from "react";
import { FileText, MessageSquare, Plus, Search, Sparkles, Table2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { documentMarkdownOptions } from "@/lib/documentMarkdown.mjs";
import FrameioPlanScreen from "./FrameioPlanScreen";

const pending = (value) => typeof value === "string" && /\{\{[^}]+\}\}/.test(value);
const label = (value) => String(value).replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]/g, " ");
const text = (value) => pending(value) ? "Available after preparation" : String(value ?? "");

// Shared rule for every workflow: a recognizable app surface comes first.
// These are previews of approved data, never fabricated live screenshots.
export function ToolScreen({ tool, title, children, sheet = false, chat = false }) {
  const Icon = sheet ? Table2 : chat ? Sparkles : FileText;
  return <section aria-label={`${tool} action preview`} className={`overflow-hidden rounded-xl border border-slate-200 text-slate-800 ${chat ? "bg-[#faf9f5]" : "bg-white"}`}>
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-[#f8fafd] px-4 py-3">
      <div className="flex min-w-0 items-center gap-3"><Icon className={`h-6 w-6 shrink-0 ${sheet ? "text-emerald-700" : chat ? "text-[#c66b4e]" : "text-blue-600"}`} />
        <div className="min-w-0"><p className="text-sm font-semibold">{tool}</p><p className="truncate text-xs text-slate-500">{title}</p></div>
      </div>
      <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-medium text-slate-500">Draft preview · Not saved yet</span>
    </header>
    {children}
  </section>;
}

function ChatDraft({ step, args, editing, onChange, editableKeys }) {
  const promptKey = ["userMessage", "prompt", "instructions", "message"].find((key) => typeof args[key] === "string");
  const prompt = args[promptKey] || "The request will be prepared from the earlier steps.";
  const tool = /claude|anthropic/i.test(`${step.tool} ${step.operation}`) ? "Claude" : step.tool || "AURA Intelligence";
  return <ToolScreen tool={tool} title="New conversation" chat>
    <div className="flex min-h-72">
      <aside className="hidden w-40 shrink-0 space-y-5 border-r border-[#e9e6df] bg-[#f0eee6] p-4 text-xs text-[#777267] sm:block">
        <p className="flex items-center gap-2 font-medium text-[#49453c]"><Plus className="h-3.5 w-3.5" />New chat</p>
        <p className="flex items-center gap-2"><Search className="h-3.5 w-3.5" />Search chats</p>
        <p className="pt-3 text-[10px] uppercase tracking-wider">This workflow</p>
        <p className="flex items-start gap-2 text-[#49453c]"><MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0" />{step.title || step.action || "Prepare content"}</p>
      </aside>
      <div className="min-w-0 flex-1 p-5 sm:p-8">
        <p className="mb-3 text-xs font-medium text-slate-500">Your request</p>
        {editing && promptKey && editableKeys.includes(promptKey) && !pending(prompt)
          ? <textarea aria-label="Request to AI" value={prompt} onChange={(event) => onChange({ ...args, [promptKey]: event.target.value })} rows={6} className="w-full resize-y rounded-2xl border border-[#d8d3c7] bg-[#f0eee6] p-4 text-sm leading-6 outline-none focus:border-[#c66b4e]" />
          : <div className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-2xl bg-[#efede6] p-4 text-sm leading-6">{text(prompt)}</div>}
        <div className="mt-6 flex items-start gap-3"><Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-[#c66b4e]" /><div><p className="text-sm font-medium">Ready to generate</p><p className="mt-1 text-xs leading-5 text-slate-500">{step.output || "The response will appear here after this step runs."}</p></div></div>
        {step.flow?.some((item) => item.label === "Backup") && <p className="mt-5 border-t border-[#e9e6df] pt-3 text-xs leading-5 text-slate-500">AURA Intelligence can take over if Claude cannot generate content. Any switch will be shown in the result.</p>}
      </div>
    </div>
  </ToolScreen>;
}

const kpis = (args) => [
  { category: "Sales", name: "Revenue", key: "revenue", format: "money" },
  { category: "Sales", name: "Orders", key: "orders" },
  { category: "Marketing", name: label(args.denominator || "sessions"), key: "denominator_value" },
  { category: "Marketing", name: "Conversions", key: "conversions" },
  { category: "Sales", name: "Average order value", numerator: "revenue", divisor: "orders", format: "money" },
  { category: "Marketing", name: "Conversion rate", numerator: "conversions", divisor: "denominator_value", format: "percent" },
];
const metricValue = (values, metric) => metric.key ? values?.[metric.key]
  : values?.[metric.divisor] > 0 ? values?.[metric.numerator] / values[metric.divisor] : null;
const formatted = (value, format) => typeof value !== "number" || !Number.isFinite(value) ? "n/a"
  : format === "money" ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value)
  : format === "percent" ? `${(value * 100).toFixed(2)}%` : value.toLocaleString("en-US");

export function KpiDraftScreen({ args, editing, onChange, editableKeys = Object.keys(args) }) {
  const [tab, setTab] = useState("KPI Dashboard");
  const change = (key, value) => onChange({ ...args, [key]: value });
  return <ToolScreen tool="Google Sheets" title={`${text(args.business_name)} · ${text(args.reporting_period)}`} sheet>
    <div className="flex flex-wrap gap-4 border-b border-slate-200 px-5 py-2 text-[11px] text-slate-500" aria-hidden="true"><span>File</span><span>Edit</span><span>View</span><span>Insert</span><span>Format</span><span>Data</span></div>
    <div className="flex items-center gap-4 border-b border-slate-200 px-4 py-2 text-xs"><span className="border-r border-slate-200 pr-4">A1</span><span className="italic text-slate-400">fx</span><span className="truncate">{text(args.business_name)} — KPI dashboard</span></div>
    {tab === "KPI Dashboard" ? <div className="overflow-x-auto">
      <div className="min-w-[660px] p-5 sm:p-7">
        <div className="mb-6 border-l-4 border-emerald-700 pl-4">
          {editing ? <><input aria-label="Business name" readOnly={!editableKeys.includes("business_name")} value={args.business_name || ""} onChange={(event) => change("business_name", event.target.value)} className="w-full border-b border-emerald-200 bg-transparent py-1 text-xl font-semibold outline-none focus:border-emerald-600" /><input aria-label="Reporting period" readOnly={!editableKeys.includes("reporting_period")} value={args.reporting_period || ""} onChange={(event) => change("reporting_period", event.target.value)} className="mt-2 border-b border-emerald-200 bg-transparent text-sm outline-none focus:border-emerald-600" /></>
            : <><h3 className="text-xl font-semibold">{text(args.business_name)}</h3><p className="mt-1 text-sm text-slate-500">KPI dashboard · {text(args.reporting_period)}</p></>}
          <p className="mt-3 text-[11px] text-slate-500">{args.illustrative ? "Illustrative template values · not actual business performance" : "User-supplied business data"}</p>
        </div>
        <table className="w-full border-collapse text-xs"><thead className="bg-[#1f4238] text-white"><tr>{["Category", "Metric", "Target", "Actual", "Variance", "Status"].map((name) => <th key={name} className="border border-[#315448] px-3 py-3 text-left font-medium">{name}</th>)}</tr></thead><tbody>
          {kpis(args).map((metric) => {
            const target = metricValue(args.target, metric), actual = metricValue(args.actual, metric);
            const known = typeof target === "number" && typeof actual === "number" && Number.isFinite(target) && Number.isFinite(actual);
            return <tr key={metric.name} className="even:bg-slate-50"><td className="border border-slate-200 px-3 py-3 text-slate-500">{metric.category}</td><td className="border border-slate-200 px-3 py-3 font-medium capitalize">{metric.name}</td>
              {["target", "actual"].map((kind) => <td key={kind} className="border border-slate-200 p-2">{editing && metric.key && editableKeys.includes(kind) ? <input type="number" min="0" step={metric.format === "money" ? "0.01" : "1"} aria-label={`${metric.name} ${kind}`} value={args[kind]?.[metric.key] ?? ""} onChange={(event) => change(kind, { ...args[kind], [metric.key]: event.target.value === "" ? "" : Number(event.target.value) })} className="w-24 rounded border border-emerald-300 bg-white px-2 py-1.5 text-right outline-none focus:ring-1 focus:ring-emerald-600" /> : <span className="block px-1 text-right tabular-nums">{formatted(metricValue(args[kind], metric), metric.format)}</span>}</td>)}
              <td className="border border-slate-200 px-3 py-3 text-right tabular-nums">{known ? formatted(actual - target, metric.format) : "n/a"}</td><td className="border border-slate-200 px-3 py-3"><span className={`whitespace-nowrap rounded px-2 py-1 text-[10px] ${known && actual >= target ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{known ? actual >= target ? "On target" : "Below target" : "n/a"}</span></td></tr>;
          })}
        </tbody></table>
        <p className="mt-4 text-[10px] leading-5 text-slate-500">Average order value = revenue ÷ orders. Conversion rate = conversions ÷ {args.denominator || "sessions"}. A zero denominator displays n/a.</p>
      </div>
    </div> : tab === "Product brief" ? <div className="min-h-64 p-6"><h3 className="mb-4 text-lg font-semibold">Product brief</h3>{editing && editableKeys.includes("product_brief") ? <textarea aria-label="Product brief" rows={8} value={args.product_brief || ""} onChange={(event) => change("product_brief", event.target.value)} className="w-full rounded-lg border border-slate-200 p-3 text-sm leading-6" /> : <p className="whitespace-pre-wrap text-sm leading-6">{text(args.product_brief) || "No product brief supplied."}</p>}</div>
      : <div className="min-h-64 p-6"><h3 className="mb-4 text-lg font-semibold">Feedback</h3><table className="w-full text-left text-xs"><thead className="bg-slate-50"><tr>{["Reviewer", "Feedback", "Status"].map((heading) => <th key={heading} className="border p-3">{heading}</th>)}</tr></thead><tbody>{(args.feedback || []).map((item, index) => <tr key={item.feedback_id || index}><td className="border p-3">{item.reviewer}</td><td className="border p-3">{item.feedback}</td><td className="border p-3">Received</td></tr>)}</tbody></table>{!args.feedback?.length && <p className="py-6 text-sm text-slate-500">Ready for reviewer feedback.</p>}</div>}
    <div role="tablist" aria-label="Workbook sheets" className="flex gap-1 overflow-x-auto border-t border-slate-200 bg-[#f8fafd] px-4 py-2">{["KPI Dashboard", "Feedback", "Product brief"].map((name) => <button key={name} type="button" role="tab" aria-selected={tab === name} onClick={() => setTab(name)} className={`whitespace-nowrap rounded px-4 py-2 text-xs ${tab === name ? "bg-emerald-100 font-semibold text-emerald-800" : "text-slate-500 hover:bg-slate-100"}`}>{name}</button>)}</div>
  </ToolScreen>;
}

export default function ToolActionScreen({ step, args = {}, editing = false, onChange = () => {}, editableKeys = Object.keys(args) }) {
  if (["frameio.file.get", "frameio.comments.list"].includes(step.operation)
    || (!step.operation && /^frame[.\s-]?io$/i.test(step.tool || step.tool_slug || ""))) return <FrameioPlanScreen step={step} />;
  if (step.operation === "sheets.kpi.create") return <KpiDraftScreen args={args} editing={editing} onChange={onChange} editableKeys={editableKeys} />;
  if (/anthropic\.chat|intelligence\.claude_backup|report\.compose/.test(step.operation || "") || ["userMessage", "prompt"].some((key) => typeof args[key] === "string")) return <ChatDraft step={step} args={args} editing={editing} onChange={onChange} editableKeys={editableKeys} />;
  const title = text(args.title || args.name || args.subject || step.title || step.action || "Prepared action");
  const body = args.body || args.content || args.text || args.description;
  const content = typeof body === "string" ? text(body) : "";
  const rows = Array.isArray(args.values) ? args.values.filter(Array.isArray) : [];
  const details = Object.entries(args).filter(([key, value]) => !/token|secret|password|api.?key|model|temperature|top[PpKk]|maxTokens/i.test(key)
    && !["title", "name", "subject", "body", "content", "text", "description", "values"].includes(key)
    && ["string", "number", "boolean"].includes(typeof value));
  return <ToolScreen tool={step.tool || "Connected app"} title={title}>
    <div className="flex min-h-64">
      <aside className="hidden w-36 shrink-0 border-r border-slate-200 bg-slate-50 p-4 text-xs text-slate-500 sm:block"><p className="mb-5 flex items-center gap-2"><Search className="h-3.5 w-3.5" />Workspace</p><p className="rounded-lg bg-white p-2 font-medium text-slate-800 shadow-sm">Prepared draft</p></aside>
      <div className="min-w-0 flex-1 p-5 sm:p-7"><h3 className="mb-4 text-xl font-semibold">{title}</h3>
        {content && <div className="max-h-80 overflow-auto whitespace-pre-wrap text-sm leading-7 [&_table]:w-full [&_td]:border [&_td]:p-2 [&_th]:border [&_th]:p-2"><ReactMarkdown {...documentMarkdownOptions}>{content}</ReactMarkdown></div>}
        {rows.length > 0 && <div className="max-h-80 overflow-auto"><table className="w-full text-xs"><tbody>{rows.map((row, index) => <tr key={index}>{row.map((cell, column) => <td key={column} className="border border-slate-200 p-3">{["string", "number", "boolean"].includes(typeof cell) ? text(cell) : ""}</td>)}</tr>)}</tbody></table></div>}
        {details.length > 0 && <dl className="mt-5 grid gap-x-5 gap-y-3 border-t border-slate-200 pt-4 text-xs sm:grid-cols-[minmax(6rem,auto)_1fr]">{details.map(([key, value]) => <div key={key} className="contents"><dt className="capitalize text-slate-500">{label(key)}</dt><dd className="break-words">{text(value)}</dd></div>)}</dl>}
        {!content && !rows.length && !details.length && <p className="text-sm leading-6 text-slate-500">{step.output || "Content will be prepared from the earlier steps before this action runs."}</p>}
      </div>
    </div>
  </ToolScreen>;
}
