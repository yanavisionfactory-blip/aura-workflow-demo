import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, ExternalLink, FileSearch, Link2, Loader2, Search } from "lucide-react";
import { ResultsHeading, ResultsMetrics } from "./ResultsSummary";
import { getPythonRun } from "@/lib/auraApi";
import { crawlInventory, crawlResult, mappedBacklog, providerOutcome, providerResultLink, runEvidence, seoAuditGroups } from "@/lib/seoAuditResult.mjs";
import { seoAuditDemoRoute } from "@/lib/seoAuditDemo.mjs";
import SimulatedSeoToolOutput from "./SimulatedSeoToolOutput";

const panel = "rounded-2xl border border-white/10 bg-[#0c1726]";
const muted = "text-xs text-slate-400";
const listText = (value) => Array.isArray(value) ? value.join(" · ") : String(value ?? "");
const statusLabel = (status) => ({ provider_error: "Provider error", completed: "Response saved", failed: "Failed", blocked: "Blocked", pending: "Not run", awaiting_approval: "Not run · awaiting review", skipped: "Skipped" })[status] || status.replaceAll("_", " ");
const decode = (value) => new TextDecoder().decode(Uint8Array.from(atob(value), (char) => char.charCodeAt(0)));
const urlLabel = (value) => { try { const url = new URL(value); return `${url.pathname}${url.search}`; } catch { return value; } };

function Badge({ children, good = false }) {
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ${good ? "bg-emerald-400/10 text-emerald-300" : "bg-amber-400/10 text-amber-200"}`}>{good ? <CheckCircle2 className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}{children}</span>;
}

function UrlTable({ rows = [], search = "", limit = 12 }) {
  const [shown, setShown] = useState(limit);
  const filtered = rows.filter((row) => `${row.url} ${row.canonical} ${row.redirect_to} ${row.csv_row}`.toLowerCase().includes(search.toLowerCase()));
  const canonical = rows.some((row) => row.canonical);
  const redirect = rows.some((row) => row.redirect_to);
  return <div>
    <div className="max-h-[32rem] overflow-auto rounded-xl border border-white/10">
      <table className="w-full text-left text-xs" aria-label="Affected URL evidence"><thead className="sticky top-0 bg-[#18263a] text-slate-300"><tr><th className="px-4 py-3">Affected URL</th>{canonical && <th className="px-4 py-3">Declared canonical</th>}{redirect && <th className="px-4 py-3">Redirects to</th>}<th className="px-4 py-3">Evidence</th></tr></thead>
        <tbody className="divide-y divide-white/5">{filtered.slice(0, shown).map((row, index) => <tr key={`${row.csv_row}-${row.url}-${index}`} className="hover:bg-white/[0.03]"><td className="min-w-48 max-w-xs break-all px-4 py-3 align-top text-slate-200" title={row.url}>{row.url ? urlLabel(row.url) : "URL mapping unavailable"}{row.status && <span className="ml-2 rounded bg-white/10 px-1.5 py-0.5 text-[10px]">{row.status}</span>}</td>{canonical && <td className="min-w-48 max-w-xs break-all px-4 py-3 align-top text-slate-400" title={row.canonical}>{row.canonical ? urlLabel(row.canonical) : "—"}</td>}{redirect && <td className="min-w-48 max-w-xs break-all px-4 py-3 align-top text-slate-400" title={row.redirect_to}>{row.redirect_to ? urlLabel(row.redirect_to) : "—"}</td>}<td className="whitespace-nowrap px-4 py-3 align-top text-slate-400">CSV row {row.csv_row ?? "—"}{row.canonical_csv_row && <span className="block">Canonical row {row.canonical_csv_row} · {row.canonical_status}</span>}{row.title_pixels !== undefined && <span className="block">Title {row.title_pixels}px · description {row.description_pixels}px</span>}{row.unique_inlinks !== undefined && <span className="block">{row.unique_inlinks} unique inlinks</span>}</td></tr>)}</tbody>
      </table>
      {!filtered.length && <p className="p-6 text-center text-sm text-slate-400">No matching URL records.</p>}
    </div>
    <div className="mt-3 flex items-center justify-between gap-3"><p className={muted}>{Math.min(shown, filtered.length)} of {filtered.length} URL records · overlapping issue groups</p>{shown < filtered.length && <button type="button" onClick={() => setShown((count) => count + 50)} className="rounded-lg border border-white/15 px-3 py-2 text-xs text-primary">Show next {Math.min(50, filtered.length - shown)} URLs</button>}</div>
  </div>;
}

function ActionReceipt({ action }) {
  return <details className="group rounded-xl border border-white/10 bg-black/10">
    <summary className="flex cursor-pointer list-none items-center gap-3 p-4 [&::-webkit-details-marker]:hidden"><Activity className="h-4 w-4 shrink-0 text-primary" /><span className="min-w-0 flex-1 break-words text-xs font-medium">{action.operation || action.action}</span><span className={muted}>{statusLabel(action.status)}</span><ChevronDown className="h-4 w-4 group-open:rotate-180" /></summary>
    <div className="space-y-4 border-t border-white/10 p-4"><p className={muted}>{action.startedAt ? `Started ${action.startedAt}` : "No start time saved"}{action.completedAt && ` · Finished ${action.completedAt}`}</p>
      <details><summary className="cursor-pointer text-xs font-medium text-primary">Inputs used</summary><pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs text-slate-300">{JSON.stringify(action.inputs, null, 2)}</pre></details>
      {action.error && <p className="break-words text-xs text-amber-200">{listText(action.error)}</p>}
      <div><p className="mb-2 text-xs font-semibold">Actual returned response</p>{action.hasResponse ? <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-black/20 p-3 text-xs text-slate-300">{JSON.stringify(action.response, null, 2)}</pre> : <p className={muted}>No response saved. This action has no research results to display.</p>}</div>
    </div>
  </details>;
}

export default function SeoAuditResult({ manifest, demo = null, snapshot = null, focus = null }) {
  const [loaded, setLoaded] = useState(demo ? { crawl: { run: demo.sourceRun } } : {});
  const [loading, setLoading] = useState(!demo);
  const [tab, setTab] = useState(focus?.tab || (demo ? "Overview" : "Affected URLs"));
  const [resultOpen, setResultOpen] = useState(Boolean(demo));
  const [selectedTool, setSelectedTool] = useState(focus?.tool || "crawl");
  const [selectedIssue, setSelectedIssue] = useState("T01");
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState(focus?.group || "");
  const [priority, setPriority] = useState(focus?.priority || "");
  // Each source run is a read-only, workspace-authorized request. Opening this
  // result never resumes the source runs or repeats provider calls.
  useEffect(() => {
    if (demo) { setLoaded({ crawl: { run: demo.sourceRun } }); setLoading(false); return undefined; }
    let active = true;
    setLoading(true); setLoaded({});
    Promise.all(manifest.references.map(async (reference) => {
      if (!reference.runId) return [reference.key, { error: "No saved run reference supplied." }];
      try { return [reference.key, { run: await getPythonRun(reference.runId) }]; }
      catch { return [reference.key, { error: "Saved output unavailable in this workspace." }]; }
    })).then((entries) => { if (active) { setLoaded(Object.fromEntries(entries)); setLoading(false); } });
    return () => { active = false; };
  }, [manifest, demo]);
  useEffect(() => {
    if (!focus) return;
    if (focus.tab) { setTab(focus.tab); setResultOpen(true); }
    if (focus.tool) setSelectedTool(focus.tool);
    if (focus.group !== undefined) setGroup(focus.group);
    if (focus.priority !== undefined) setPriority(focus.priority);
  }, [focus]);
  const crawl = useMemo(() => snapshot?.crawl || crawlResult(loaded.crawl?.run), [snapshot, loaded]);
  const inventory = useMemo(() => snapshot?.inventory || crawlInventory(loaded.crawl?.run, decode), [snapshot, loaded]);
  const backlog = useMemo(() => snapshot?.backlog || mappedBacklog(manifest.backlog, inventory), [snapshot, manifest, inventory]);
  const tools = snapshot ? [{ key: "crawl", name: "Screaming Frog", state: "returned", label: "Export analysed", message: `${crawl.counts.url_records} URL records · anonymized supplied export`, actions: [] }] : manifest.references.map((reference) => {
    const saved = loaded[reference.key];
    const outcome = reference.key === "crawl"
      ? { state: crawl ? "returned" : "unavailable", label: crawl ? "Export analysed" : "Output unavailable", message: crawl ? `${crawl.counts.url_records} URL records · supplied export` : saved?.error || "Opening saved output…", actions: runEvidence(saved?.run, reference.name) }
      : providerOutcome(saved?.run, reference.name);
    return { ...reference, ...outcome, error: saved?.error, run: saved?.run };
  });
  if (demo) tools.push(...demo.tools);
  else tools.push({ key: "sitebulb", name: "Sitebulb", state: "unavailable", label: "No output supplied", message: manifest.sourceNotes.sitebulb || "No saved Sitebulb output supplied.", actions: [] });
  const issue = crawl?.issues?.find((item) => item.id === selectedIssue) || crawl?.issues?.[0];
  const tool = tools.find((item) => item.key === selectedTool) || tools[0];
  const openTool = (key) => {
    setSelectedTool(key); setTab("Tool activity"); setResultOpen(true);
    if (snapshot) window.setTimeout(() => document.getElementById("audit-view")?.scrollIntoView({ block: "start", behavior: "smooth" }), 100);
  };
  const counts = crawl?.counts;
  const ready = tools.filter((item) => item.state === "returned").length;
  const first = backlog.find((item) => item.priority === "P1");
  return <section aria-label="Main workflow result" className="space-y-6 text-slate-100">
    {demo && <div role="note" aria-label="Demo data disclosure" className="rounded-xl border border-violet-400/30 bg-violet-400/10 px-4 py-3 text-xs leading-6 text-violet-200"><strong>DEMO · Real Screaming Frog data + 3 simulated tools.</strong> Semrush, Ahrefs and Sitebulb values are realistic examples created for this preview. No provider calls, documents, tickets or site changes are made.</div>}
    <ResultsHeading centered isFailure={!demo && !loading && ready < 4}
      title={demo ? "SEO audit demo prepared" : loading ? "Opening SEO audit review…" : ready === 4 ? "SEO audit review prepared" : "SEO audit review needs access"}
      summary={crawl ? demo ? `${crawl.website} · Real crawl evidence combined with a labelled research scenario. Open each tool to inspect its output.` : `${crawl.website} · ${ready} of 4 sources returned audit data. The review and proposed backlog are saved in AURA.` : "Opening the saved source outputs and implementation backlog."} />
    {!demo && crawl && seoAuditDemoRoute(loaded.crawl?.run?.id) && <p className="text-center text-xs"><Link className="text-primary hover:underline" to={seoAuditDemoRoute(loaded.crawl.run.id)}>Preview with simulated Semrush, Ahrefs and Sitebulb outputs</Link></p>}
    <ResultsMetrics metrics={[
      { value: counts?.url_records ?? "—", label: "crawl URL records imported" },
      { value: counts?.canonical_conflicts ?? "—", label: "canonical conflicts observed" },
      { value: backlog.length, label: "implementation items proposed" },
    ]} />
    {loading && <p role="status" className="flex items-center gap-2 text-sm text-primary"><Loader2 className="h-4 w-4 animate-spin" />Loading saved tool outcomes…</p>}
    <section aria-label="What happened">
      <h3 className="mb-3 text-sm font-semibold">What happened</h3>
      <div className="space-y-2">{tools.map((item) => <div key={item.key} className={`flex flex-wrap items-center gap-3 rounded-xl border p-4 ${item.simulated ? "border-violet-400/20 bg-violet-400/[0.04]" : item.state === "returned" ? "border-white/10 bg-card/40" : "border-amber-400/20 bg-amber-400/[0.04]"}`}>
        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${item.simulated ? "bg-violet-400/10 text-violet-300" : item.state === "returned" ? "bg-primary/10 text-primary" : "bg-amber-400/10 text-amber-300"}`}>{item.state === "returned" || item.simulated ? <FileSearch className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}</span>
        <div className="min-w-0 flex-1"><p className="text-sm font-medium">{item.key === "crawl" && crawl ? `${counts.url_records} Screaming Frog URL records imported` : `${item.name} · ${item.label.toLowerCase()}`}</p><p className="mt-1 text-[11px] leading-5 text-muted-foreground">{item.key === "crawl" ? (snapshot ? "REAL · Anonymized export findings; CSV row references and file hashes preserved." : "REAL · Supplied exports analysed in AURA; source files and CSV rows retained.") : item.simulated ? `SIMULATED · ${item.message}` : item.key === "sitebulb" ? "OAuth registration rejected by Sitebulb; a completed audit is still needed." : item.error || item.message}</p></div>
        {providerResultLink(item.run) && <a href={providerResultLink(item.run)} target="_blank" rel="noopener noreferrer" className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-primary/25 px-3 py-1.5 text-[11px] text-primary">Open in {item.name}<ExternalLink className="h-3 w-3" /></a>}
        <button type="button" onClick={() => openTool(item.key)} aria-label={`View ${item.name} ${item.simulated ? "simulated output" : item.state === "returned" ? "output" : "issue"}`} className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] ${item.state === "returned" || item.simulated ? "border-primary/25 text-primary" : "border-amber-400/25 text-amber-300"}`}>{item.simulated ? "View demo output" : item.state === "returned" ? "View output" : "View issue"}<ArrowRight className="h-3 w-3" /></button>
      </div>)}
      <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-card/40 p-4"><span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><FileSearch className="h-4 w-4" /></span><div className="flex-1"><p className="text-sm font-medium">{backlog.length} implementation items prepared</p><p className="mt-1 text-[11px] text-muted-foreground">Affected URLs, evidence, fixes, effort, dependencies and expert checks.</p></div><button type="button" onClick={() => { setGroup(""); setPriority(""); setTab("Backlog"); setResultOpen(true); }} className="shrink-0 rounded-full border border-primary/25 px-3 py-1.5 text-[11px] text-primary">View backlog</button></div>
      </div>
    </section>
    <section aria-label="Tools used" className="rounded-xl border border-white/10 bg-card/40 p-4">
      <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-semibold">Tools used</h3><button type="button" onClick={() => openTool(selectedTool)} className="inline-flex items-center gap-1.5 rounded-full border border-primary/25 px-3 py-1.5 text-[11px] text-primary"><Activity className="h-3 w-3" />View activity</button></div>
      <div className="mt-3 flex flex-wrap gap-2">{tools.map((item) => <button key={item.key} type="button" onClick={() => openTool(item.key)} className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-[11px]">{item.state === "returned" ? <CheckCircle2 className="h-3 w-3 text-emerald-300" /> : <AlertTriangle className="h-3 w-3 text-amber-300" />}{item.name}{item.simulated && <span className="text-[9px] uppercase text-violet-300">Demo</span>}</button>)}</div>
    </section>
    <details open={resultOpen} onToggle={(event) => setResultOpen(event.currentTarget.open)} className="group rounded-2xl border border-white/10 bg-card/20">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-4 text-sm font-semibold [&::-webkit-details-marker]:hidden"><FileSearch className="h-4 w-4 text-primary" />Results <span className="text-xs font-normal text-muted-foreground">{demo ? "— real crawl + simulated research" : "— the actual output"}</span><ChevronDown className="ml-auto h-4 w-4 text-muted-foreground group-open:rotate-180" /></summary>
      <div className="px-4 pb-5">
        <div className="mb-5 flex gap-1 overflow-x-auto border-b border-white/10" role="tablist" aria-label="Audit result views">{["Affected URLs", "Backlog", "Overview", "Tool activity", "Sources & intake"].map((name) => <button key={name} id={`audit-tab-${name.replaceAll(" ", "-")}`} type="button" role="tab" aria-selected={tab === name} aria-controls="audit-view" onClick={() => setTab(name)} className={`shrink-0 border-b-2 px-3 py-3 text-xs font-medium ${tab === name ? "border-primary text-primary" : "border-transparent text-slate-400 hover:text-white"}`}>{name}</button>)}</div>
    <div id="audit-view" role="tabpanel" aria-labelledby={`audit-tab-${tab.replaceAll(" ", "-")}`} className="space-y-5">
      {tab === "Overview" && <>
        <div className="grid gap-4 md:grid-cols-[1.4fr_1fr]">
          {first && <div className="rounded-2xl border border-amber-400/25 bg-amber-400/[0.04] p-5"><p className="text-[10px] font-semibold uppercase tracking-widest text-amber-300">First priority · {first.id} · {first.priority}</p><h3 className="mt-2 text-lg font-semibold">{first.title}</h3><div className="mt-4 flex flex-wrap gap-2"><span className="rounded-lg bg-white/5 px-2.5 py-1.5 text-xs">{first.affected.length} affected URLs</span><span className="rounded-lg bg-white/5 px-2.5 py-1.5 text-xs">{first.kind}</span></div><button type="button" onClick={() => { setSelectedIssue(first.id); setTab("Affected URLs"); }} className="mt-4 inline-flex items-center gap-2 text-xs font-medium text-primary">Inspect URL evidence <ArrowRight className="h-3.5 w-3.5" /></button></div>}
          <div className={`${panel} p-5`}><h3 className="text-sm font-semibold">Backlog by workstream</h3><div className="mt-4 space-y-3">{seoAuditGroups.map((name) => { const count = backlog.filter((item) => item.group.toLowerCase() === name.toLowerCase()).length; return <button type="button" key={name} onClick={() => { setGroup(name); setPriority(""); setTab("Backlog"); }} className="flex w-full items-center gap-3 text-left text-xs"><span className="w-28 shrink-0 text-slate-300">{name}</span><span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5"><span className="block h-full rounded-full bg-primary/70" style={{ width: `${count / backlog.length * 100}%` }} /></span><span className="w-4 text-right text-slate-400">{count}</span></button>; })}</div><p className="mt-4 text-[10px] text-slate-500">Backlog items, including evidence gaps. URL scopes overlap.</p></div>
        </div>
        <section aria-label="Prioritized roadmap"><h3 className="mb-3 text-sm font-semibold">Implementation roadmap</h3><div className="grid gap-3 sm:grid-cols-3">{[["P1", "Resolve URL policy"], ["P2", "Validate and fill evidence gaps"], ["P3", "Optimise content and navigation"]].map(([level, label], index) => <button key={level} type="button" onClick={() => { setGroup(""); setPriority(level); setTab("Backlog"); }} className={`${panel} p-4 text-left hover:border-primary/40`}><p className="text-[10px] font-semibold text-primary">{index + 1} · {level}</p><p className="mt-2 text-xs font-medium">{label}</p><p className="mt-2 text-[11px] text-slate-400">{backlog.filter((item) => item.priority === level).length} proposed items →</p></button>)}</div><p className="mt-2 text-[10px] text-slate-500">Proposed sequence. Confirm dependencies and effort before implementation.</p></section>
        {counts && <div className={`${panel} p-5`}><div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold">Crawl response codes</h3><span className={muted}>{counts.html_200} HTML pages · {counts.url_records} resources</span></div><div className="flex h-4 overflow-hidden rounded-full bg-white/5" aria-label={`${counts.http_status?.["200"]} HTTP 200 resources, ${counts.http_status?.["307"]} HTTP 307 redirects`}>{Object.entries(counts.http_status || {}).map(([status, number]) => <div key={status} className={status === "200" ? "bg-emerald-400/80" : "bg-sky-400/80"} style={{ width: `${number / counts.url_records * 100}%` }} />)}</div><div className="mt-3 flex gap-5 text-xs"><span className="text-emerald-300">● {counts.http_status?.["200"]} HTTP 200</span><span className="text-sky-300">● {counts.http_status?.["307"]} HTTP 307</span></div></div>}
        {crawl && <div><div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold">Canonical conflict · source evidence</h3><button type="button" onClick={() => setTab("Affected URLs")} className="text-xs text-primary">View all findings →</button></div><UrlTable key="overview" rows={crawl.issues?.find((item) => item.id === "T01")?.affected || []} limit={5} /></div>}
      </>}
      {tab === "Affected URLs" && <>
        <div className="flex flex-wrap gap-2">{(crawl?.issues || []).map((item) => <button key={item.id} type="button" aria-pressed={issue?.id === item.id} onClick={() => { setSelectedIssue(item.id); setSearch(""); }} className={`rounded-xl border px-3 py-2 text-xs ${issue?.id === item.id ? "border-primary/50 bg-primary/10 text-primary" : "border-white/10 text-slate-400"}`}>{item.id} · {item.affected.length} URLs</button>)}</div>
        {issue ? <><div className={`${panel} p-5`}><div className="flex flex-wrap items-center gap-2"><Badge good={issue.state === "Observed"}>{issue.state}</Badge><span className={muted}>{issue.group} · {issue.priority}</span></div><h3 className="mt-3 font-semibold">{issue.title}</h3><p className="mt-2 text-sm text-slate-400">{issue.reasoning}</p><p className="mt-4 text-xs text-slate-300"><strong className="text-primary">Proposed fix</strong> · {listText(issue.fix)}</p><p className="mt-3 text-xs text-slate-400">Effort: {listText(issue.effort)} · Dependencies: {listText(issue.dependencies)}</p></div><label className="flex items-center gap-2 rounded-xl border border-white/10 px-3 py-2"><Search className="h-4 w-4 text-slate-500" /><input aria-label="Filter affected URLs" placeholder="Filter URLs or CSV rows" value={search} onChange={(event) => setSearch(event.target.value)} className="w-full bg-transparent text-sm outline-none" /></label><UrlTable key={issue.id} rows={issue.affected} search={search} /></> : <p className="text-sm text-slate-400">{loaded.crawl?.error || "No crawl findings available."}</p>}
      </>}
      {tab === "Backlog" && <><div className="flex flex-wrap items-center gap-2" role="group" aria-label="Backlog groups">{["", ...seoAuditGroups].map((name) => <button type="button" key={name} aria-pressed={group === name} onClick={() => setGroup(name)} className={`rounded-full border px-3 py-1.5 text-xs ${group === name ? "border-primary/50 bg-primary/10 text-primary" : "border-white/10 text-slate-400"}`}>{name || "All groups"}</button>)}<select aria-label="Backlog priority" value={priority} onChange={(event) => setPriority(event.target.value)} className="rounded-lg border border-white/10 bg-[#0c1726] px-3 py-2 text-xs"><option value="">All priorities</option>{["P1", "P2", "P3"].map((value) => <option key={value}>{value}</option>)}</select></div><p className={muted}>Proposed implementation work · provisional effort · no tasks created or site changes made</p><div className="space-y-2">{backlog.filter((item) => (!group || item.group.toLowerCase() === group.toLowerCase()) && (!priority || item.priority === priority)).map((item) => <details key={item.id} open={focus?.issue === item.id ? true : undefined} className={`group ${panel}`}><summary className="flex cursor-pointer list-none items-start gap-3 p-4 [&::-webkit-details-marker]:hidden"><span className={`rounded-lg px-2 py-1 text-xs font-semibold ${item.priority === "P1" ? "bg-amber-400/15 text-amber-300" : "bg-white/5 text-slate-400"}`}>{item.priority}</span><span className="flex-1"><span className="text-sm font-medium">{item.id} · {item.title}</span><span className="mt-1 block text-[11px] text-slate-400">{item.group} · {item.kind} · {item.affected.length} scoped URLs</span></span><ChevronDown className="h-4 w-4 shrink-0 text-slate-500 group-open:rotate-180" /></summary><div className="space-y-4 border-t border-white/10 p-4">{[["Evidence", item.evidence], ["Proposed fix", item.fix], ["Effort", item.effort], ["Dependencies", item.dependencies], ["Priority reasoning", item.reasoning], ["Expert review", item.expert_review], ["Acceptance check", item.acceptance]].map(([name, value]) => <div key={name}><p className="text-[11px] font-semibold text-primary">{name}</p><p className="mt-1 text-xs leading-6 text-slate-300">{listText(value)}</p></div>)}<UrlTable key={item.id} rows={item.affected} /></div></details>)}</div></>}
      {tab === "Tool activity" && <>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Choose tool output">{tools.map((item) => <button key={item.key} type="button" aria-pressed={tool.key === item.key} onClick={() => setSelectedTool(item.key)} className={`rounded-xl border px-3 py-2 text-xs ${tool.key === item.key ? "border-primary/50 bg-primary/10 text-primary" : "border-white/10 text-slate-400"}`}>{item.name}{item.simulated && <span className="text-[9px] uppercase text-violet-300">Demo</span>}</button>)}</div>
        <div className={`${panel} p-5`}><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">{tool.name} output</h3><Badge good={tool.state === "returned"}>{tool.label}</Badge></div><div className="mt-4 flex items-start gap-3">{tool.state === "returned" ? <FileSearch className="mt-1 h-5 w-5 shrink-0 text-emerald-300" /> : <AlertTriangle className="mt-1 h-5 w-5 shrink-0 text-amber-300" />}<div>{tool.code && <p className="mb-1 font-mono text-sm text-amber-200">{tool.code}</p>}<p className="text-sm leading-6 text-slate-300">{tool.error || tool.message}</p>{!tool.simulated && tool.state !== "returned" && <p className="mt-2 text-xs text-slate-500">{tool.key === "sitebulb" || tool.key === "crawl" ? "No technical audit findings are available from this outcome." : "No keyword, visibility or backlink metrics are available from this outcome."}</p>}</div></div>
          <div className="mt-5 flex flex-wrap items-center gap-4 border-t border-white/10 pt-4">{tool.runId && <Link to={`/runs/${tool.runId}`} target="_blank" className="inline-flex items-center gap-1.5 text-xs text-primary">Open saved action <ExternalLink className="h-3 w-3" /></Link>}{providerResultLink(tool.run) ? <a href={providerResultLink(tool.run)} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-xs text-primary">Open result in {tool.name}<ExternalLink className="h-3 w-3" /></a> : <span className={muted}>{tool.simulated ? "Simulated preview · no vendor report exists" : tool.key === "crawl" ? "Desktop export · evidence displayed in AURA" : "No provider report URL returned"}</span>}</div>
        </div>
        {tool.key === "crawl" && crawl && <div className="space-y-3">{crawl.issues.map((item) => <button key={item.id} type="button" onClick={() => { setSelectedIssue(item.id); setTab("Affected URLs"); }} className={`flex w-full items-center gap-3 ${panel} p-4 text-left`}><Link2 className="h-4 w-4 shrink-0 text-primary" /><span className="flex-1 text-xs">{item.id} · {item.title}</span><span className={muted}>{item.affected.length} URLs</span><ArrowRight className="h-3 w-3" /></button>)}</div>}
        {tool.simulated && <SimulatedSeoToolOutput tool={tool} website={crawl?.website} scenarioDate={demo.scenarioDate} />}
        <div className="space-y-2">{tool.actions.map((action) => <ActionReceipt key={action.id} action={action} />)}</div>
        {!tool.simulated && !tool.actions.length && <p className={muted}>No executed action receipt is available. The status above is from the supplied source packet.</p>}
      </>}
      {tab === "Sources & intake" && <>
        <div className={`${panel} p-5`}><h3 className="text-sm font-semibold">Crawl dates and source files</h3><p className="mt-3 text-xs text-slate-300">{crawl?.crawl_period?.first_raw || "Not supplied"} → {crawl?.crawl_period?.last_raw || "Not supplied"}</p><p className="mt-1 text-xs text-slate-500">Timezone: {crawl?.crawl_period?.timezone || "Not supplied"} · Export created: {crawl?.crawl_period?.export_created_at || "Not supplied"} · Settings unconfirmed</p><div className="mt-4 space-y-3">{(crawl?.files || []).map((file, index) => <details key={`${file.filename}-${index}`} className="rounded-xl border border-white/10 p-3"><summary className="cursor-pointer text-xs"><span className="font-medium">{file.filename}</span><span className="ml-3 text-slate-400">{file.rows} rows · {Array.isArray(file.columns) ? file.columns.length : file.columns} columns{file.duplicate_of ? " · duplicate bytes" : ""}</span></summary><p className="mt-3 break-all font-mono text-[10px] text-slate-500">SHA256 {file.sha256}</p>{file.duplicate_of && <p className="mt-2 text-xs text-amber-200">Duplicate of {file.duplicate_of}. Not independent crawl evidence.</p>}</details>)}</div></div>
        <div className={`${panel} p-5`}><h3 className="text-sm font-semibold">Client, goals and destinations</h3><p className="mt-3 text-xs leading-6 text-slate-300">{manifest.sourceNotes.intake}</p></div>
        <div className={`${panel} p-5`}><h3 className="text-sm font-semibold">Contradictions and checks</h3><ul className="mt-3 space-y-2 text-xs leading-6 text-slate-400">{[...(demo?.checks || []), ...(crawl?.warnings || []), ...(crawl?.unverified_checks || [])].map((warning, index) => <li key={index} className="flex gap-2"><AlertTriangle className="mt-1 h-3 w-3 shrink-0 text-amber-300" /><span>{listText(warning)}</span></li>)}</ul></div>
      </>}
    </div>
      </div>
    </details>
  </section>;
}
