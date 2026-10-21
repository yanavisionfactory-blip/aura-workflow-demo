import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Activity, AlertTriangle, ArrowRight, BarChart3, Check, CheckCircle2, ChevronDown, Download, ExternalLink, Eye, FlaskConical, Mail, Plus, RefreshCw, Share2, Wrench } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { marketingToolStates } from '@/lib/marketingToolResults.mjs';
import MarketingToolResults from './MarketingToolResults';

const card = 'rounded-xl border border-white/10 bg-[#0c121e]/65';
const smallButton = 'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-full border border-cyan-400/25 px-3 py-1.5 text-[11px] font-medium text-cyan-300 transition hover:bg-cyan-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300';
const outlineButton = 'inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium transition hover:bg-white/10';
const details = {
  google: ['Google Ads account discovery', 'Native read only · client match not verified'],
  meta: ['Meta Ads campaign simulation', 'Synthetic weekly comparison and two creative concepts'],
  mailchimp: ['Mailchimp audience discovery', 'Native audience metadata · invitation remains a proposal'],
  klaviyo: ['Klaviyo lifecycle simulation', 'Synthetic email results, checkout recovery and repeat-purchase drafts'],
};

export default function MarketingResultsSummary({packet,activity=[],onDownload,sourceRunId}) {
  const [searchParams,setSearchParams] = useSearchParams();
  const requestedView=searchParams.get('tool');
  const view=['google','meta','mailchimp','klaviyo','activity','approvals'].includes(requestedView)?requestedView:null;
  const setView=next=>setSearchParams(previous=>{
    const params=new URLSearchParams(previous);
    if(next) params.set('tool',next);else params.delete('tool');
    return params;
  },{replace:true});
  const [copied,setCopied] = useState(false);
  const [shareError,setShareError] = useState('');
  const states = marketingToolStates(activity);
  const nativeCount = states.filter(tool=>tool.mode==='Native' && tool.status==='completed').length;
  const simulationCount = states.filter(tool=>tool.mode==='Simulated' && tool.status==='completed').length;
  const brief = packet.simulations[0].brief;
  const download = () => {
    if(onDownload) return onDownload();
    const url=URL.createObjectURL(new Blob([JSON.stringify({packet,activity},null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='AURA_Marketing_Tool_Outputs.json';link.click();URL.revokeObjectURL(url);
  };
  const share = async () => {
    try { await navigator.clipboard.writeText(window.location.href);setCopied(true);setShareError(''); }
    catch { setShareError('The link could not be copied. Copy this page’s address to share it. Workspace access is still required.'); }
  };
  const isTool = states.some(tool=>tool.key===view);
  return <section aria-label="Marketing workflow results" className="mx-auto w-full max-w-3xl">
    <header className="mb-6 text-center">
      <div className="mx-auto mb-4 flex h-[58px] w-[58px] items-center justify-center rounded-2xl border border-emerald-400/25 bg-emerald-400/[0.08] shadow-[0_0_35px_rgba(52,211,153,0.08)]"><CheckCircle2 className="h-7 w-7 text-emerald-400"/></div>
      <h1 className="text-2xl font-bold tracking-tight">{simulationCount===2 ? 'Marketing campaign review ready' : 'Marketing workflow results'}</h1>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-400">Meta Ads and Klaviyo simulations, with native Google Ads and Mailchimp discovery checks, prepared for account-manager review.</p>
      <p className="mt-2 text-[11px] text-slate-500">Maple & Ember Coffee · fictional client · all assets are unsaved proposals</p>
    </header>

    <div aria-label="Workflow totals" className="mb-7 grid grid-cols-3 gap-3">
      {[[nativeCount,'native checks completed'],[simulationCount,'simulated tool outputs'],[0,'launches or sends']].map(([value,label])=><div key={label} className={`${card} px-2 py-4 text-center`}><p className="text-2xl font-bold tracking-tight">{value}</p><p className="mt-1 text-[11px] leading-5 text-slate-400">{label}</p></div>)}
    </div>

    <section aria-label="What happened" className="mb-6">
      <h2 className="mb-3 text-sm font-semibold">What happened</h2>
      <div className="space-y-2">{states.map(tool=>{
        const Icon=tool.mode==='Simulated'?FlaskConical:tool.key==='mailchimp'?Mail:BarChart3;
        return <div key={tool.key} className={`${card} flex flex-wrap items-center gap-3 px-3 py-3 sm:flex-nowrap`}>
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-400/10 text-violet-400"><Icon className="h-4 w-4"/></span>
          <div className="min-w-0 flex-1"><h3 className="text-sm font-medium">{details[tool.key][0]}</h3><p className="mt-1 text-[11px] leading-5 text-slate-400">{tool.status==='completed'?details[tool.key][1]:tool.label+' · open the tool for details'}</p></div>
          <button type="button" aria-label={`View ${tool.name} output`} onClick={()=>setView(tool.key)} className={smallButton}><ExternalLink className="h-3 w-3"/>View {tool.name}</button>
        </div>;
      })}
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-amber-400/30 bg-amber-400/[0.045] px-3 py-3 sm:flex-nowrap">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-400/10 text-amber-400"><AlertTriangle className="h-4 w-4"/></span>
          <div className="min-w-0 flex-1"><h3 className="text-sm font-medium">Client matching and implementation approvals remain open</h3><p className="mt-1 text-[11px] leading-5 text-slate-400">Verify accounts, destinations, events and audience rules before implementation.</p></div>
          <button type="button" onClick={()=>setView('approvals')} className={`${smallButton} border-amber-400/30 text-amber-300`}><Eye className="h-3 w-3"/>View issue</button>
        </div>
      </div>
    </section>

    <section aria-label="Tools used" className={`${card} mb-5 p-4`}>
      <div className="mb-3 flex items-center justify-between gap-3"><h2 className="flex items-center gap-2 text-sm font-semibold"><Wrench className="h-3.5 w-3.5 text-slate-500"/>Tools used</h2><button type="button" onClick={()=>setView('activity')} className="inline-flex items-center gap-1 rounded-full border border-violet-400/20 px-2.5 py-1 text-[11px] text-violet-400"><Activity className="h-3 w-3"/>View activity</button></div>
      <div className="flex flex-wrap gap-2">{states.map(tool=><button type="button" key={tool.key} aria-label={`View ${tool.name} results`} onClick={()=>setView(tool.key)} className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2 text-[11px] font-medium hover:border-violet-400/40">{tool.status==='completed'?<Check className="h-3 w-3 text-emerald-400"/>:<AlertTriangle className="h-3 w-3 text-amber-400"/>}{tool.name}{tool.mode==='Simulated' && <span className="text-[10px] text-violet-300">Simulated</span>}</button>)}</div>
    </section>

    <details className="group mb-6">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-2 text-sm font-semibold [&::-webkit-details-marker]:hidden"><BarChart3 className="h-4 w-4 text-violet-400"/>Results<span className="text-[11px] font-normal text-slate-400">— the actual output</span><ChevronDown className="h-3.5 w-3.5 text-slate-400 transition group-open:rotate-180"/></summary>
      <div className={`${card} mt-3 divide-y divide-white/10 px-4`}>{states.map(tool=><div key={tool.key} className="flex items-center justify-between gap-3 py-3"><span className="text-xs">{tool.name}<span className="ml-2 text-[10px] text-slate-400">{tool.mode}</span></span><button type="button" onClick={()=>setView(tool.key)} className="text-xs text-cyan-300">Open tool output<ArrowRight className="ml-1 inline h-3 w-3"/></button></div>)}</div>
    </details>

    <section aria-label="Suggested next" className="mb-5"><h2 className="mb-3 flex items-center gap-2 text-sm font-semibold"><ArrowRight className="h-4 w-4 text-violet-400"/>Suggested next</h2><div className="flex flex-wrap gap-2">{[['meta','Review the Meta creative test'],['klaviyo','Review recovery and retention emails'],['approvals','Confirm the client accounts and approvals']].map(([key,label])=><button type="button" key={key} onClick={()=>setView(key)} className="rounded-full border border-violet-400/20 px-3 py-1.5 text-xs text-violet-400 hover:bg-violet-400/10">{label}</button>)}</div></section>

    <section className="rounded-2xl border border-violet-400/15 bg-violet-400/[0.035] p-4"><h2 className="text-sm font-semibold">What would you like to do next?</h2><p className="mt-1 text-[11px] leading-5 text-slate-400">Review the proposed actions, run it again, or start something new.</p><div className="mt-3 grid gap-2 sm:grid-cols-3"><Link className={outlineButton} to="/marketing-tools"><RefreshCw className="h-4 w-4"/>Run again</Link><button type="button" onClick={()=>setView('approvals')} className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-500 to-sky-400 px-4 py-3 text-sm font-semibold text-white shadow-[0_5px_20px_rgba(139,92,246,0.15)]"><CheckCircle2 className="h-4 w-4"/>Review approvals</button><Link className={outlineButton} to="/"><Plus className="h-4 w-4"/>New workflow</Link></div></section>

    <footer className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/10 pt-4 text-xs"><button type="button" className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2" onClick={()=>setView('activity')}><Activity className="h-3.5 w-3.5"/>Activity</button><button type="button" className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2" onClick={share}>{copied?<Check className="h-3.5 w-3.5"/>:<Share2 className="h-3.5 w-3.5"/>}{copied?'Link copied':'Share'}</button><button type="button" className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2" onClick={download}><Download className="h-3.5 w-3.5"/>Download</button>{sourceRunId && <Link to={`/runs/${sourceRunId}`} className="ml-auto inline-flex items-center gap-1.5 py-2 text-[11px] text-slate-400">Native source run<ExternalLink className="h-3 w-3"/></Link>}</footer>
    {shareError && <p role="status" className="mt-3 text-xs text-amber-200">{shareError}</p>}

    <Dialog open={Boolean(view)} onOpenChange={open=>{if(!open)setView(null);}}><DialogContent className="flex max-h-[90dvh] w-[calc(100vw-1.5rem)] max-w-7xl flex-col overflow-hidden rounded-2xl border-white/15 bg-[#0a111d] p-0"><div className="border-b border-white/10 px-5 py-4 pr-12"><DialogTitle>{isTool?states.find(tool=>tool.key===view).name+' output':view==='activity'?'Workflow activity':'Before implementation'}</DialogTitle><DialogDescription className="mt-2 text-xs leading-5">{isTool?'Interface imitation inside AURA. Review the tool output and proposals; this is not a live vendor screen.':view==='activity'?'Native discovery reads and explicitly simulated adapter executions.':'Open approvals for this fictional client scenario. No implementation is authorized by this review.'}</DialogDescription></div><div className={`min-h-0 overflow-y-auto ${isTool?'':'p-4 sm:p-5'}`}>
      {isTool?<MarketingToolResults key={view} packet={packet} activity={activity} initialTool={view} compact/>:view==='activity'?<ol className="space-y-3">{states.map(tool=><li key={tool.key} className={`${card} p-4`}><h3 className="text-sm font-semibold">{tool.name} · {tool.mode}</h3><p className="mt-2 text-xs text-slate-400">{tool.label}</p><p className="mt-2 break-all text-xs text-slate-500">{tool.operation}</p><p className="mt-2 text-xs leading-5 text-slate-400">{tool.mode==='Simulated'?'Browser simulation adapter · vendor API not called · no external writes':'Native discovery only · does not verify a client match'}</p><button type="button" onClick={()=>setView(tool.key)} className="mt-3 text-xs text-cyan-300">View response and evidence<ArrowRight className="ml-1 inline h-3 w-3"/></button></li>)}</ol>:<div className="space-y-5 text-sm leading-7"><p className="rounded-xl border border-amber-400/25 bg-amber-400/5 p-4">{brief.native_limit}</p><h3 className="font-semibold">Shared campaign and approved scenario offers</h3><p>{brief.status}</p><p>{brief.objective}</p><p>{brief.offer}</p><p>{brief.retention_offer}</p><p>{brief.audience_ownership}</p><p className="break-all text-xs text-slate-400">{brief.destination} · {brief.destination_status}</p><h3 className="font-semibold">Platform approvals</h3><ul className="list-disc space-y-3 pl-5"><li><strong>Google Ads:</strong> Match the client account, approve conversion definition, copy, targeting and test settings.</li><li><strong>Meta Ads:</strong> Confirm account, approved creative, audience, measurement and spending cap.</li><li><strong>Mailchimp:</strong> Verify permissioned non-purchasers, purchaser and Klaviyo exclusions, sender and copy.</li><li><strong>Klaviyo:</strong> Validate checkout/order events, consent, suppression sync and existing-flow conflicts before approving messages and timing.</li></ul><p className="text-xs text-slate-400">Simulation links use a reserved .example destination. Assets remain proposals in this review; no native campaigns, flows or messages were saved.</p></div>}
    </div></DialogContent></Dialog>
  </section>;
}
