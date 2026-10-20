import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { documentMarkdownOptions } from "@/lib/documentMarkdown.mjs";
import ToolEvidence from "./ToolEvidence";

export default function CampaignReportResult({ preview, campaign, activity = [] }) {
  const [selected, setSelected] = useState("Brief");
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
    {selected === "Tool outputs" ? <ToolEvidence activity={activity} initiallyOpen /> : <div className="aura-article-preview rounded-2xl bg-slate-50 px-6 py-7 text-sm leading-7 text-slate-700 sm:px-9">
      {selected === "Brief" && campaign.intro && <ReactMarkdown {...documentMarkdownOptions}>{campaign.intro}</ReactMarkdown>}
      {group?.sections.map((section) => <article key={section.title} className="mb-7 last:mb-0"><ReactMarkdown {...documentMarkdownOptions}>{section.body}</ReactMarkdown></article>)}
    </div>}
    <details className="rounded-xl border border-white/10 p-5"><summary className="cursor-pointer text-xs font-medium text-primary">Complete saved report and source evidence</summary>
      <div className="aura-article-preview mt-4 rounded-xl bg-slate-50 p-6 text-sm leading-7 text-slate-700"><ReactMarkdown {...documentMarkdownOptions}>{preview.body}</ReactMarkdown></div>
      {(preview.sources || []).map((source) => <details key={source.id} className="mt-3 rounded-xl border border-white/10 p-4"><summary className="cursor-pointer text-xs">[{source.id}] {source.title}</summary><p className="mt-3 whitespace-pre-wrap break-words text-xs leading-6 text-muted-foreground">{source.content}</p></details>)}
    </details>
  </section>;
}
