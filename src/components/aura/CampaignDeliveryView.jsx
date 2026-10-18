import { useState } from "react";
import { ExternalLink, FileText, ShieldCheck } from "lucide-react";
import PrimaryResult from "./PrimaryResult";
import { ResultsHeading, ResultsMetrics } from "./ResultsSummary";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const box = "rounded-2xl border border-white/10 bg-card/60";
export default function CampaignDeliveryView({ data, onSave, saving, error }) {
  const [selected, setSelected] = useState("0");
  const concepts = data.channels.reduce((n, c) => n + c.drafts.length, 0);
  return <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 md:py-12">
    <ResultsHeading heading="h1" eyebrow={`${data.agency} · Workflow results`} title={data.title} summary={data.summary} />
    <ResultsMetrics metrics={[{ value: data.channels.length, label: "channel draft sets" }, { value: concepts, label: "complete draft concepts" }, { value: data.approvals.filter((a) => a.status !== "Not applicable").length, label: "review actions remaining" }]} />
    <PrimaryResult title="Your campaign launch package" provider="AURA" providerVerb="Prepared in" footer={<span className="flex items-center gap-2 text-emerald-300"><ShieldCheck className="h-4 w-4" />Fictional client · All placements unpublished · No media spend committed</span>}>
      <p className="mb-5 text-xs leading-6 text-muted-foreground">Review the channel copy below. Budget, dates, destination accounts and approved assets still need agency confirmation.</p>
      <Tabs value={selected} onValueChange={setSelected}>
        <TabsList aria-label="Campaign channels" className="mb-5 h-auto max-w-full flex-wrap justify-start bg-black/15 p-1">{data.channels.map((c, i) => <TabsTrigger className="px-4 py-2 text-xs data-[state=active]:bg-primary/20" key={c.name} value={String(i)}>{c.name}</TabsTrigger>)}</TabsList>
        {data.channels.map((channel, index) => <TabsContent key={channel.name} value={String(index)} className="mt-0">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2 text-xs"><span className="text-primary">{channel.scope}</span><span className="text-muted-foreground">Drafts for review</span></div>
          <div className="space-y-4">{channel.drafts.map((draft) => <article key={draft.id} className="overflow-hidden rounded-2xl border border-white/10 bg-[#f8fafc] text-slate-700">
            <div className="border-b border-slate-200 px-6 py-5"><p className="text-[10px] font-semibold uppercase tracking-wider text-violet-600">{data.client} · Demonstration copy</p><h3 className="mt-2 text-xl font-semibold text-slate-900">{draft.title}</h3></div>
            <dl className="space-y-5 px-6 py-6">{draft.fields.map((field, i) => <div key={`${field.label}:${i}`}><dt className="text-[11px] font-medium text-slate-500">{field.label}{field.limit ? ` · ${field.text.length}/${field.limit} characters` : ""}</dt><dd className="mt-1.5 whitespace-pre-wrap text-sm leading-7">{field.text}</dd></div>)}</dl>
          </article>)}</div>
        </TabsContent>)}
      </Tabs>
    </PrimaryResult>
    <section className="mt-7"><h2 className="mb-4 text-sm font-medium">Results in your tools</h2><div className="space-y-3">{(data.links || []).map((l) => <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer" className={`${box} flex items-center justify-between gap-4 p-5 hover:border-primary/30`}><span><span className="text-[10px] text-primary">{l.tool}</span><span className="mt-1 block text-sm">{l.label}</span></span><ExternalLink className="h-4 w-4 shrink-0 text-primary" /></a>)}</div></section>
    <section className={`${box} mt-6 p-6`}><h2 className="text-base font-medium">The demonstration brief</h2><p className="mt-3 text-sm leading-7 text-slate-300">{data.brief.goal}</p><dl className="mt-4 grid gap-4 text-xs sm:grid-cols-2">{Object.entries(data.brief).filter(([k]) => k !== "goal").map(([k,v]) => <div key={k}><dt className="capitalize text-muted-foreground">{k.replace(/([A-Z])/g, " $1")}</dt><dd className="mt-1.5 leading-6">{Array.isArray(v) ? v.join(", ") : v}</dd></div>)}</dl></section>
    <details className={`${box} mt-4 p-6`}><summary className="cursor-pointer text-sm font-medium">Asset checklist</summary><div className="mt-4 overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr>{["Asset", "Status", "Requirement / next step"].map((v) => <th key={v} className="border-b border-white/10 p-3 font-medium text-muted-foreground">{v}</th>)}</tr></thead><tbody>{data.assets.map((a) => <tr key={a.id}><td className="border-b border-white/5 p-3">{a.name}</td><td className="border-b border-white/5 p-3 text-primary">{a.status}</td><td className="border-b border-white/5 p-3 leading-6 text-muted-foreground">{a.requirement}</td></tr>)}</tbody></table></div></details>
    <details className={`${box} mt-4 p-6`}><summary className="cursor-pointer text-sm font-medium">Approval tracker and launch handoff</summary><div className="mt-4 space-y-3">{data.approvals.map((a) => <div key={a.id} className="border-b border-white/10 pb-3 text-xs"><div className="flex justify-between gap-4"><span>{a.item}</span><span className="shrink-0 text-amber-200">{a.status}</span></div><p className="mt-1.5 leading-6 text-muted-foreground">{a.owner} · {a.action}</p></div>)}</div><h3 className="mt-6 text-sm font-medium">Implementation steps</h3><ol className="mt-3 list-decimal space-y-3 pl-4 text-xs leading-6 text-muted-foreground">{data.manualSteps.map((s) => <li key={s}>{s}</li>)}</ol></details>
    <details className={`${box} mt-4 p-6`}><summary className="cursor-pointer text-sm font-medium">Consistency checks and execution record</summary><ul className="mt-4 list-disc space-y-3 pl-4 text-xs leading-6 text-muted-foreground">{data.consistency.map((s) => <li key={s}>{s}</li>)}</ul><div className="mt-5 space-y-3 text-xs leading-6">{Object.entries(data.execution).map(([k,v]) => <p key={k}><strong className="capitalize">{k}: </strong>{Array.isArray(v) ? v.join(" ") : v}</p>)}</div></details>
    <section className={`${box} mt-4 p-6`}><h2 className="text-sm font-medium">Feedback for Maverick Digital</h2><ol className="mt-4 list-decimal space-y-3 pl-4 text-xs leading-6 text-muted-foreground">{data.questions.map((q) => <li key={q}>{q}</li>)}</ol></section>
    {error && <p role="alert" className="mt-5 text-sm text-amber-200">{error}</p>}
    {onSave && <button disabled={saving} onClick={onSave} className="mt-6 inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-medium disabled:opacity-50"><FileText className="h-4 w-4" />{saving ? "Saving…" : "Save campaign review"}</button>}
  </main>;
}
