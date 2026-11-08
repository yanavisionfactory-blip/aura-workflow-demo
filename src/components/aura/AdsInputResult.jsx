import { useState } from "react";
import { BarChart3, CheckCircle2, Database, SearchX } from "lucide-react";
import { adsInputResult } from "@/lib/adsInputResult.mjs";

const columns = ["Spend", "Impressions", "Clicks", "CTR", "CPC", "Conversions", "CPA", "Conversion value", "ROAS"];
const fact = (item, label) => item?.facts.find((value) => value.label === label)?.value;

export default function AdsInputResult({ tool, entries, isPrimary = false }) {
  const model = adsInputResult(entries);
  const [selected, setSelected] = useState("");
  const [tab, setTab] = useState("campaigns");
  const dataset = model.datasets.find((item) => item.entry.id === selected) || model.datasets[0] || model.summaries[0];
  const allEmpty = model.datasets.length > 0 && model.datasets.every((item) => item.empty);
  const records = dataset?.campaigns || [];
  const currency = fact(dataset, "Currency");
  const meta = tool === "Meta Ads";
  const campaigns = records.length > 0 || entries.some((entry) => /campaign|insights/.test(entry.operation));
  return <section aria-label={`${tool} result screen`} className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white text-slate-900 shadow-sm">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-4 py-4 sm:px-5">
      <div className="flex items-center gap-3"><span className={`flex h-10 w-10 items-center justify-center rounded-xl ${meta ? "bg-blue-100 text-blue-600" : "bg-green-100 text-green-700"}`}><BarChart3 className="h-5 w-5" /></span><div><h4 className="font-semibold">{tool} · {campaigns ? "Campaigns" : "Saved data"}</h4><p className="mt-0.5 text-xs text-slate-500">Saved source data in AURA</p></div></div>
      <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600"><Database className="h-3.5 w-3.5" />{isPrimary ? "Main result" : "Used as input"}</span>
    </header>
    {model.discovery && <section aria-label="Automatic account discovery" className="space-y-2 border-b border-slate-200 bg-amber-50 px-4 py-4 text-xs leading-5 sm:px-5">
      <h5 className="font-semibold">{model.discovery.coverage?.status === "complete" ? "Accounts detected automatically" : "Account discovery needs attention"}</h5>
      <ul>{(model.discovery.accounts || []).map((account) => <li key={account.ad_account_id || account.id}>{account.name || "Advertising account"} · {account.ad_account_id || account.id}{account.currency ? ` · ${account.currency}` : ""}</li>)}</ul>
      {(model.discovery.coverage?.warnings || []).map((warning, index) => <p key={index}>{warning}</p>)}
      <p>Account discovery uses the existing connection. Accounts listed here may not all have been included in this saved report. A new workflow checks accounts again automatically.</p>
    </section>}
    <div className="border-b border-slate-200 px-4 pt-4 sm:px-5">
      <p className="mb-4 text-xs leading-5 text-slate-500">Data retrieved for this workflow. This is a saved AURA view, not the live ads manager.</p>
      <div role="tablist" aria-label={`${tool} saved data views`} className="flex gap-5">
        {[["campaigns", campaigns ? "Campaign data" : "Saved data"], ["coverage", "Accounts & coverage"]].map(([value, label]) => <button type="button" key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)} className={`min-h-11 border-b-2 text-sm font-medium ${tab === value ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500"}`}>{label}</button>)}
      </div>
    </div>
    {tab === "campaigns" ? <div className="space-y-5 p-4 sm:p-5">
      {model.datasets.length > 1 && !allEmpty && <label className="block text-xs font-medium text-slate-500">Saved report<select aria-label={`${tool} saved report`} value={dataset.entry.id} onChange={(event) => setSelected(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-300 bg-white p-2.5 text-sm text-slate-800">{model.datasets.map((item) => <option key={item.entry.id} value={item.entry.id}>{item.label}</option>)}</select></label>}
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-500"><span>Account: <strong className="font-medium text-slate-700">{allEmpty && model.accounts.length > 1 ? `${model.accounts.length} accounts · see coverage` : fact(dataset, "Account") || "Unavailable"}</strong></span>{currency && !(allEmpty && model.accounts.length > 1) && <span>Currency: <strong className="font-medium text-slate-700">{currency}</strong></span>}{!allEmpty && <span>{fact(dataset, "Reporting dates") || fact(dataset, "Reporting scope")}</span>}</div>
      {dataset?.records.length || dataset?.body ? <div className="space-y-4"><h5 className="font-semibold">{dataset.entry.action}</h5>{dataset.body && <p className="whitespace-pre-wrap break-words text-sm leading-6">{dataset.body}</p>}<ul className="divide-y divide-slate-200">{dataset.records.map((record, index) => <li key={index} className="py-3 text-sm"><p className="font-medium">{record.title}</p>{record.description && <p className="mt-1 text-slate-500">{record.description}</p>}</li>)}</ul></div> : records.length > 0 ? <>
        <div className="flex items-center gap-2 text-sm font-medium"><CheckCircle2 className="h-4 w-4 text-emerald-600" />{records.length} campaign {records.length === 1 ? "result" : "results"}</div>
        {records.length === 1 && <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">{records[0].metrics.filter((metric) => ["Spend", "Impressions", "Clicks", "Conversions"].includes(metric.label)).map((metric) => <div key={metric.label} className="rounded-xl bg-slate-50 p-3"><dt className="text-xs text-slate-500">{metric.label}{metric.label === "Spend" && (records[0].currency || currency) ? ` (${records[0].currency || currency})` : ""}</dt><dd className="mt-2 break-words text-xl font-semibold tabular-nums">{metric.value}</dd></div>)}</dl>}
        <div className="space-y-3 md:hidden">{records.map((campaign, index) => <article key={index} className="rounded-xl border border-slate-200 p-4"><h5 className="font-semibold">{campaign.title}</h5><p className="mt-1 text-xs text-slate-500">{[campaign.status, campaign.currency || currency, campaign.dates].filter(Boolean).join(" · ")}</p><dl className="mt-4 grid grid-cols-2 gap-4">{campaign.metrics.map((metric) => <div key={metric.label}><dt className="text-xs text-slate-500">{metric.label}</dt><dd className="mt-1 font-medium tabular-nums">{metric.value}</dd></div>)}</dl></article>)}</div>
        <div className="hidden max-w-full overflow-x-auto rounded-lg border border-slate-200 md:block"><table className="w-full text-left text-xs"><caption className="sr-only">{tool} saved campaign metrics</caption><thead className="bg-slate-50 text-slate-500"><tr><th className="p-3 font-medium">Campaign</th>{columns.map((column) => <th key={column} className="whitespace-nowrap p-3 font-medium">{column}</th>)}</tr></thead><tbody>{records.map((campaign, index) => <tr key={index} className="border-t border-slate-200"><th className="min-w-36 p-3 font-medium">{campaign.title}<span className="mt-1 block text-[11px] font-normal text-slate-500">{[campaign.status, campaign.currency || currency, campaign.dates].filter(Boolean).join(" · ")}</span></th>{campaign.metrics.map((metric) => <td key={metric.label} className="whitespace-nowrap p-3 tabular-nums">{metric.value}</td>)}</tr>)}</tbody></table></div>
      </> : <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-5 py-8 text-center"><SearchX className="mx-auto mb-3 h-8 w-8 text-slate-400" /><h5 className="font-semibold">{allEmpty ? "No campaign records returned" : "No campaign metrics in this saved response"}</h5><p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">{allEmpty ? "Metrics are unavailable, not zero. The connected account and reporting periods are recorded below." : "Account discovery or another source action completed. See accounts and coverage for the saved details."}</p></div>}
      {allEmpty && <div><h5 className="mb-2 text-xs font-semibold text-slate-600">Reporting periods checked</h5><ul className="flex flex-wrap gap-2">{[...new Set(model.datasets.map((item) => fact(item, "Reporting dates")).filter(Boolean))].map((date) => <li key={date} className="rounded-md bg-slate-100 px-2.5 py-1.5 text-xs text-slate-600">{date}</li>)}</ul><p className="mt-3 text-xs leading-5 text-slate-500">No returned records does not establish that earlier history or other accounts have no activity.</p></div>}
      {dataset?.note && !allEmpty && <p className="text-xs leading-5 text-slate-500">{dataset.note}</p>}
    </div> : <div className="divide-y divide-slate-200 px-4 sm:px-5">{model.summaries.map((item) => <section key={item.entry.id} className="py-4"><h5 className="text-sm font-semibold">{item.entry.action}</h5><p className="mt-1 text-xs text-slate-500">{item.summary}</p><dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">{item.facts.map(({label,value}) => <div key={label}><dt className="text-slate-500">{label}</dt><dd className="mt-1 break-words font-medium">{value}</dd></div>)}</dl></section>)}</div>}
  </section>;
}
