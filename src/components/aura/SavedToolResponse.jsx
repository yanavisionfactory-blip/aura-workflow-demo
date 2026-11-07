import { savedToolResponse } from "@/lib/savedToolResponse.mjs";

export default function SavedToolResponse({ entry }) {
  const result = savedToolResponse(entry);
  return <div className="min-w-0 space-y-4 text-sm">
    {result.title && <h4 className="font-semibold">{result.title}</h4>}
    {result.body && <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-200">{result.body}</p>}
    <p className={result.empty ? "rounded-xl border border-amber-300/20 bg-amber-300/5 p-4 leading-6 text-amber-100" : "leading-6 text-slate-300"}>{result.summary}</p>
    {result.facts.length > 0 && <dl className="grid gap-x-5 gap-y-3 sm:grid-cols-2">{result.facts.map(({ label, value }) => <div key={label} className="min-w-0"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words text-sm text-slate-200">{value}</dd></div>)}</dl>}
    {result.campaigns.map((campaign, index) => <section key={index} className="rounded-xl border border-white/10 p-4">
      <h4 className="font-semibold">{campaign.title}</h4><p className="mt-1 text-xs text-muted-foreground">{[campaign.status, campaign.currency].filter(Boolean).join(" · ")}</p>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 lg:grid-cols-5">{campaign.metrics.map(({ label, value }) => <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words text-base font-semibold tabular-nums">{value}</dd></div>)}</dl>
    </section>)}
    {result.records.length > 0 && <ul className="divide-y divide-white/10">{result.records.map((row, index) => <li key={index} className="py-3"><p className="font-medium">{row.title}</p>{row.description && <p className="mt-1 text-xs text-muted-foreground">{row.description}</p>}</li>)}</ul>}
    {result.note && <p className="text-xs leading-5 text-muted-foreground">{result.note}</p>}
  </div>;
}
