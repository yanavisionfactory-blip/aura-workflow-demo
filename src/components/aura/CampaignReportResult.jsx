import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { documentMarkdownOptions } from "@/lib/documentMarkdown.mjs";
import { getPythonRun } from "@/lib/auraApi";
import { campaignSourceRunIds, campaignDeliveryRows, campaignApplicationGroup, campaignRunActivity, campaignActivityForGroup } from "@/lib/campaignToolResults.mjs";
import ToolEvidence from "./ToolEvidence";

function DeliveryStatus({ rows, onOpen, groups }) {
  if (!rows.length) return null;
  const text = (value) => <ReactMarkdown {...documentMarkdownOptions}>{value}</ReactMarkdown>;
  return <section aria-label="Application preparation status" className="rounded-2xl border border-white/10 p-5">
    <h3 className="text-sm font-semibold">Prepared outputs and remaining actions</h3>
    <p className="mt-2 text-xs leading-6 text-muted-foreground">This is the saved campaign summary. Execution receipts below show which platform actions actually ran.</p>
    <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-xs leading-6"><thead><tr>{["Actual application", "Action completed", "Saved output/link", "Remaining action"].map((label) => <th key={label} className="min-w-40 px-3 py-2 font-semibold text-primary">{label}</th>)}</tr></thead>
      <tbody className="divide-y divide-white/10">{rows.map((row, index) => {
        const target = campaignApplicationGroup(row.application, groups);
        return <tr key={index}><td className="px-3 py-3 align-top">{target && onOpen ? <button type="button" onClick={() => onOpen(target)} className="text-left font-medium text-primary hover:underline">{row.application} →</button> : text(row.application)}</td>
          {[row.completed, row.saved, row.remaining].map((value, cell) => <td key={cell} className="min-w-48 max-w-sm px-3 py-3 align-top text-muted-foreground">{text(value)}</td>)}</tr>;
      })}</tbody></table></div>
  </section>;
}

function CampaignReceipts({ selected, activity, references, loaded, loading }) {
  const current = campaignActivityForGroup(activity, selected);
  const saved = references.map((id) => ({ id, ...loaded[id], activity: campaignActivityForGroup(campaignRunActivity(loaded[id]?.run), selected) }));
  return <section aria-label="Campaign execution evidence" className="space-y-4">
    <h3 className="text-sm font-semibold">Saved execution evidence</h3>
    {loading && <p role="status" className="text-xs text-muted-foreground">Opening earlier source checks saved in AURA…</p>}
    {current.length > 0 && <div><p className="mb-3 text-xs font-medium text-primary">This report run</p><ToolEvidence activity={current} initiallyOpen /></div>}
    {saved.filter((source) => source.activity.length || source.error).map((source) => <div key={source.id} className="rounded-xl border border-white/10 p-4">
      <p className="mb-3 text-xs text-muted-foreground">Earlier source run · <Link to={`/runs/${source.id}`} target="_blank" className="text-primary hover:underline">Open saved source results</Link></p>
      {source.error ? <p className="text-xs text-amber-200">{source.error}</p> : <ToolEvidence activity={source.activity} initiallyOpen />}
    </div>)}
    {!loading && !current.length && !saved.some((source) => source.activity.length) && <p className="rounded-xl border border-amber-400/20 bg-amber-400/5 p-4 text-sm text-amber-100">No matching platform action receipt is available in these saved runs. The campaign material above is an AURA preparation draft.</p>}
    {references.length > 0 && <p className="text-xs leading-6 text-muted-foreground">Earlier checks keep their original run and status. Opening this page reads saved results; it does not repeat provider actions.</p>}
  </section>;
}

export default function CampaignReportResult({ preview, campaign, activity = [] }) {
  const [selected, setSelected] = useState("Brief");
  const references = useMemo(() => campaignSourceRunIds(preview.sources), [preview.sources]);
  const delivery = useMemo(() => campaignDeliveryRows(preview.body), [preview.body]);
  const [loaded, setLoaded] = useState({});
  const [loading, setLoading] = useState(references.length > 0);
  useEffect(() => {
    let active = true;
    setLoaded({}); setLoading(references.length > 0);
    Promise.all(references.map(async (id) => {
      try {
        const run = await getPythonRun(id);
        if (run?.id !== id) throw new Error("Unexpected saved run");
        return [id, { run }];
      } catch { return [id, { error: "Saved source results are unavailable in this workspace." }]; }
    })).then((entries) => { if (active) { setLoaded(Object.fromEntries(entries)); setLoading(false); } });
    return () => { active = false; };
  }, [references]);
  const groupNames = campaign.groups.map((item) => item.name);
  const groupDelivery = delivery.filter((row) => campaignApplicationGroup(row.application, groupNames) === selected);
  const group = campaign.groups.find((item) => item.name === selected);
  return <section aria-label="Campaign launch package" className="space-y-5">
    <div><p className="text-xs font-medium text-primary">Unpublished review package</p>
      <h2 className="mt-2 text-2xl font-semibold">{preview.title}</h2>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">Review the campaign content and each tool’s saved output here. Channel copy is a draft; provider access and human approvals are shown separately.</p>
    </div>
    <div role="group" aria-label="Campaign result views" className="flex flex-wrap gap-2">
      {[...campaign.groups.map((item) => item.name), "Tool outputs"].map((name) => <button key={name} type="button" aria-pressed={selected === name}
        onClick={() => setSelected(name)} className={`rounded-xl border px-4 py-2.5 text-xs font-medium ${selected === name ? "border-primary/60 bg-primary/15 text-primary" : "border-white/15 text-muted-foreground hover:border-primary/30"}`}>{name}</button>)}
    </div>
    <DeliveryStatus rows={selected === "Tool outputs" ? delivery : groupDelivery} onOpen={selected === "Tool outputs" ? setSelected : null} groups={groupNames} />
    {selected !== "Tool outputs" && <div className="aura-article-preview rounded-2xl bg-slate-50 px-6 py-7 text-sm leading-7 text-slate-700 sm:px-9">
      {selected === "Brief" && campaign.intro && <ReactMarkdown {...documentMarkdownOptions}>{campaign.intro}</ReactMarkdown>}
      {group?.sections.map((section) => <article key={section.title} className="mb-7 last:mb-0"><ReactMarkdown {...documentMarkdownOptions}>{section.body}</ReactMarkdown></article>)}
    </div>}
    {selected !== "Brief" && <CampaignReceipts selected={selected} activity={activity} references={references} loaded={loaded} loading={loading} />}
    <details className="rounded-xl border border-white/10 p-5"><summary className="cursor-pointer text-xs font-medium text-primary">Complete saved report and source evidence</summary>
      <div className="aura-article-preview mt-4 rounded-xl bg-slate-50 p-6 text-sm leading-7 text-slate-700"><ReactMarkdown {...documentMarkdownOptions}>{preview.body}</ReactMarkdown></div>
      {(preview.sources || []).map((source) => <details key={source.id} className="mt-3 rounded-xl border border-white/10 p-4"><summary className="cursor-pointer text-xs">[{source.id}] {source.title}</summary><p className="mt-3 whitespace-pre-wrap break-words text-xs leading-6 text-muted-foreground">{source.content}</p></details>)}
    </details>
  </section>;
}
