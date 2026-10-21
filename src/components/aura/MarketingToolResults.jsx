import { useState } from 'react';
import { FlaskConical, ShieldCheck } from 'lucide-react';
import { marketingToolStates } from '@/lib/marketingToolResults.mjs';
import { EvidenceValue } from './ToolEvidence';
import MarketingNativeScreen from './MarketingNativeScreen';

const panel = 'rounded-xl border border-white/10 bg-[#0c1422]';
const money = value => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(value);
const valueFor = (key,value) => value == null ? 'Unavailable' : key.endsWith('_rate') ? `${(value*100).toFixed(3)}%`
  : /spend|revenue|cpa/.test(key) ? money(value) : Number(value).toLocaleString('en-US');
const labelFor = key => ({purchase_cpa:'Purchase CPA',clicks_rate:'Click rate',unsubscribes_rate:'Unsubscribe rate'}[key] || key.replaceAll('_',' '));

function Draft({draft}) {
  return <article className={`${panel} overflow-hidden`}>
    <div className="border-b border-white/10 px-5 py-4"><h4 className="font-semibold">{draft.title}</h4><p className="mt-1 text-xs text-violet-200">{draft.status}</p></div>
    <div className="space-y-4 p-5 text-sm leading-7">
      {draft.subject_options && <div><p className="text-xs text-muted-foreground">Subject options</p>{draft.subject_options.map(subject=><p key={subject}>{subject}</p>)}</div>}
      {draft.preheader && <p className="text-muted-foreground">{draft.preheader}</p>}
      {draft.headlines && <div><p className="text-xs text-muted-foreground">Headlines</p>{draft.headlines.map(text=><p key={text}>{text}</p>)}<p className="mt-3 text-xs text-muted-foreground">Descriptions</p>{draft.descriptions.map(text=><p key={text}>{text}</p>)}</div>}
      <div className="rounded-xl bg-slate-50 p-5 text-slate-900"><p className="font-semibold">Maple & Ember Coffee</p><p className="mt-3">{draft.primary_text || draft.body}</p>{draft.headline && <h5 className="mt-4 font-bold">{draft.headline}</h5>}<span className="mt-4 inline-block rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white">{draft.cta} · preview</span></div>
      {['concept','trigger','eligibility','suppression'].map(key=>draft[key] && <div key={key}><h5 className="font-semibold capitalize">{key}</h5><p className="text-muted-foreground">{draft[key]}</p></div>)}
      <details className="rounded-lg border border-white/10 p-3"><summary className="cursor-pointer text-xs">Tracked destination · simulation placeholder</summary><p className="mt-2 break-all text-xs text-muted-foreground">{draft.url}</p><p className="mt-2 text-xs text-muted-foreground">Reserved .example host. Replace and validate the destination before implementation.</p></details>
    </div>
  </article>;
}

export function MarketingToolOutput({packet}) {
  if (!packet) return null;
  return <div className="space-y-5">
    <div className="rounded-xl border border-violet-400/25 bg-violet-400/5 p-4 text-sm leading-7 text-violet-100"><strong>{packet.tool} · Simulated tool adapter</strong><p>Synthetic scenario and mock responses. This adapter executed in AURA's browser; the vendor API was not called. Drafts are retained in this review with no native campaign or flow created.</p></div>
    <p className="text-xs leading-6 text-muted-foreground">{packet.periods.current.from}–{packet.periods.current.to} versus {packet.periods.previous.from}–{packet.periods.previous.to} · {packet.timezone} · {packet.currency}<br/>{packet.attribution}</p>
    <section className={`${panel} overflow-auto`}><table className="w-full text-left text-sm"><caption className="p-4 text-left font-semibold">Simulated weekly performance</caption><thead className="bg-white/5"><tr><th className="p-3">Metric</th><th className="p-3">Previous week</th><th className="p-3">Latest week</th></tr></thead><tbody>{Object.keys(packet.comparison.current).map(key=><tr key={key} className="border-t border-white/10"><th className="p-3 font-medium capitalize">{labelFor(key)}</th><td className="p-3 tabular-nums">{valueFor(key,packet.comparison.previous[key])}</td><td className="p-3 tabular-nums">{valueFor(key,packet.comparison.current[key])}</td></tr>)}</tbody></table></section>
    <section className="space-y-3"><h3 className="font-semibold">Evidence and opportunity</h3>{packet.findings.map(item=><article className={`${panel} p-4`} key={item.finding}><p className="text-sm leading-7">{item.finding}</p><p className="mt-2 text-xs text-muted-foreground">{item.evidence.join(' · ')}</p></article>)}</section>
    <section className="space-y-3"><h3 className="font-semibold">{packet.tool === 'Meta Ads' ? 'Creative concepts' : 'Recovery and repeat-purchase emails'}</h3><div className="grid gap-4 lg:grid-cols-2">{packet.drafts.map(draft=><Draft key={draft.id} draft={draft}/>)}</div></section>
    <section className={`${panel} space-y-3 p-5 text-sm leading-7`}><h3 className="font-semibold">Proposed experiment · {packet.test.platform}</h3><p>{packet.test.action}</p>{packet.test.audience && <p className="text-muted-foreground">{packet.test.audience}</p>}<p><strong>Expected learning:</strong> {packet.test.learning}</p><p><strong>Approval needed:</strong> {packet.test.approval}</p></section>
    {packet.routing_checks && <details className={`${panel} p-4`}><summary className="cursor-pointer text-sm font-semibold">Simulated audience routing checks</summary><div className="mt-4"><EvidenceValue value={packet.routing_checks}/></div></details>}
    <details className={`${panel} p-4`}><summary className="cursor-pointer text-sm font-semibold">Source rows and execution receipt</summary><div className="mt-4 space-y-4"><EvidenceValue value={packet.rows}/><EvidenceValue value={packet.receipt}/></div></details>
  </div>;
}

export default function MarketingToolResults({packet,activity=[],initialTool='meta',compact=false,initialSection}) {
  const [selected,setSelected] = useState(initialTool);
  const states = marketingToolStates(activity);
  const current = states.find(tool=>tool.key===selected);
  const fallback = packet.simulations.find(item=>item.tool===current.name);
  const brief = packet.simulations[0].brief;
  const response = current.response?.kind === 'marketing_tool' ? current.response : fallback;
  return <section aria-label="Marketing workflow tool results" className="mb-6 space-y-5">
    {!compact && <><header><p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Campaign workspace</p><h1 className="mt-3 text-2xl font-semibold sm:text-3xl">Meet your morning coffee</h1><p className="mt-2 text-sm text-muted-foreground">Maple & Ember Coffee · fictional client · account-manager review</p></header>
    <section className={`${panel} p-5`}><h2 className="font-semibold">One campaign, four tool views</h2><p className="mt-2 text-sm leading-7 text-muted-foreground">{brief.objective}</p><p className="mt-3 text-sm leading-7">{brief.offer}</p><p className="mt-3 text-xs leading-6 text-muted-foreground">AURA coordinates the workflow. Native Google Ads and Mailchimp checks retain their actual responses; Meta Ads and Klaviyo use authorized simulation adapters.</p></section></>}
    {!compact && <div role="tablist" aria-label="Marketing tools" className="grid grid-cols-2 gap-3 sm:grid-cols-4">{states.map(tool=><button key={tool.key} role="tab" aria-selected={selected===tool.key} onClick={()=>setSelected(tool.key)} className={`rounded-xl border p-4 text-left ${selected===tool.key?'border-primary/50 bg-primary/10':'border-white/10 bg-card/30'}`}><span className="flex items-center gap-2 text-sm font-semibold">{tool.mode==='Simulated'?<FlaskConical className="h-4 w-4 text-violet-300"/>:<ShieldCheck className="h-4 w-4 text-emerald-300"/>}{tool.name}</span><span className="mt-2 block text-xs text-muted-foreground">{tool.mode} · {tool.label}</span></button>)}</div>}
    <div role="tabpanel" aria-label={`${current.name} output`}><MarketingNativeScreen key={current.key} current={current} packet={response} brief={brief} initialSection={initialSection}/></div>
    <details className={`${panel} p-5`}><summary className="cursor-pointer text-sm font-semibold">Shared brief, offers and channel ownership</summary><div className="mt-4 space-y-3 text-sm leading-7"><p>{brief.status}</p>{brief.products.map(item=><p key={item}>{item}</p>)}<p>{brief.retention_offer}</p><p>{brief.shipping}</p><p>{brief.audience_ownership}</p><p className="break-all text-xs text-muted-foreground">{brief.destination} · {brief.destination_status}</p></div></details>
  </section>;
}
