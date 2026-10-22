import {useState} from 'react';
import {Activity,ArrowRight,BarChart3,CheckCircle2,ChevronDown,Download,FileCheck2,GitBranch,Mail,Play,Search} from 'lucide-react';
import MarketingNativeScreen from '@/components/aura/MarketingNativeScreen';
import {brief,packets,tools,toolState,approvals,downloadPacket} from './data.mjs';

function Disclosure({id,title,summary,icon:Icon,autoOpen=false,children}) {
  const [open,setOpen]=useState(autoOpen);
  return <details id={`demo-${id}`} className="mdemo-disclosure" open={open} onToggle={event=>setOpen(event.currentTarget.open)}>
    <summary><span className="mdemo-disclosure-icon"><Icon size={17}/></span><span><strong>{title}</strong><small>{summary}</small></span><ChevronDown size={16} className={open?'mdemo-chevron-open':''}/></summary>
    {open&&<div className="mdemo-disclosure-content">{children}</div>}
  </details>;
}

function Measurement() {
  const money=value=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value);
  return <div className="mdemo-detail-pad"><h3>Two weeks, separate platform attribution</h3><p className="mdemo-muted">October 12–18 versus October 5–11, 2026 · America/New_York · USD. These are synthetic figures.</p><div className="mdemo-measurement-grid">{[
    ['Meta Ads',packets.meta,[['spend','Spend'],['purchases','Purchase credits'],['revenue','Attributed revenue'],['purchase_cpa','Purchase CPA']]],
    ['Klaviyo',packets.klaviyo,[['delivered','Delivered'],['clicks','Clicks'],['orders','Order credits'],['revenue','Attributed revenue'],['unsubscribes','Unsubscribes']]],
  ].map(([name,packet,metrics])=><section key={name}><h4>{name}</h4><table><thead><tr><th>Metric</th><th>Previous</th><th>Latest</th></tr></thead><tbody>{metrics.map(([key,label])=><tr key={key}><th>{label}</th>{['previous','current'].map(period=><td key={period}>{/spend|revenue|cpa/.test(key)?money(packet.comparison[period][key]):packet.comparison[period][key]}</td>)}</tr>)}</tbody></table><p>{packet.attribution}</p></section>)}</div><p className="mdemo-note">Do not add the platforms’ attributed order or revenue credits together. Google Ads and Mailchimp show proposed assets and fictional discovery examples, without a claimed performance report.</p></div>;
}

export default function MarketingDemoResults({focus=null,onWatch,onStart}) {
  const download=()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify(downloadPacket(),null,2)],{type:'application/json'}));
    const anchor=document.createElement('a');anchor.href=url;anchor.download='AURA_Marketing_Demo_Draft_Pack.json';anchor.click();URL.revokeObjectURL(url);
  };
  return <div className="mdemo-results">
    <header className="mdemo-outcome-heading"><span className="mdemo-complete"><CheckCircle2 size={15}/>Campaign drafts ready for review</span><h1>Meet your morning coffee</h1><p>One coordinated acquisition and retention campaign for Maple & Ember Coffee.</p><div className="mdemo-offer"><strong>Shared offer</strong><span>{brief.offer}</span></div></header>

    <section id="demo-main-outcome" aria-label="Main campaign outcome" className="mdemo-primary">
      <div className="mdemo-primary-heading"><div><span>MAIN OUTCOME · META ADS</span><h2>Two creative variations, ready to review</h2></div><span className="mdemo-proposal-label">Proposed · not published</span></div>
      <div className="mdemo-primary-screen" tabIndex={0} aria-label="Main Meta Ads creative screen"><MarketingNativeScreen current={toolState('meta')} packet={packets.meta} brief={brief} initialSection="ads" demoMode/></div>
      <div className="mdemo-primary-footer"><CheckCircle2 size={14}/><span>Primary text, headlines, calls to action, ad preview and test proposal. Use the draft selector to compare both variations.</span></div>
    </section>

    <section aria-label="Supporting outputs" className="mdemo-supporting"><div className="mdemo-supporting-heading"><h2>Supporting outputs</h2><span>Open only what you need</span></div>
      <Disclosure id="google" title="Google Ads" summary="Two matching Search ad variations · same offer and destination" icon={Search} autoOpen={focus==='google'}><MarketingNativeScreen current={toolState('google')} brief={brief} initialSection="ads" demoMode/></Disclosure>
      <Disclosure id="mailchimp" title="Mailchimp" summary="Prospect invitation · two subjects, email copy and tracked CTA" icon={Mail} autoOpen={focus==='mailchimp'}><MarketingNativeScreen current={toolState('mailchimp')} brief={brief} initialSection="email" demoMode/></Disclosure>
      <Disclosure id="klaviyo" title="Klaviyo" summary="Checkout recovery and repeat-purchase flow proposals" icon={GitBranch} autoOpen={focus==='klaviyo'}><MarketingNativeScreen current={toolState('klaviyo')} packet={packets.klaviyo} brief={brief} initialSection="flows" demoMode/></Disclosure>
      <Disclosure id="coordination" title="How AURA coordinated the tools" summary="One brief, one offer, distinct audience ownership and draft-only actions" icon={Activity} autoOpen={focus==='coordination'}><div className="mdemo-detail-pad"><h3>Four tools, one campaign</h3><p>{brief.objective}</p><div className="mdemo-coordination-grid">{tools.map(tool=><article key={tool.key}><span>{tool.name}</span><h4>{tool.role}</h4><p>{tool.output}</p></article>)}</div><h4>Audience rules</h4><p>{brief.audience_ownership}</p><h4>Shared scenario facts</h4>{brief.products.map(product=><p key={product}>{product}</p>)}<p>{brief.retention_offer}</p><p>{brief.shipping}</p><p className="mdemo-note">The public walkthrough uses fictional account IDs and synthetic data for every tool. AURA coordinates these prepared outputs. Each tool keeps its own drafts and evidence.</p></div></Disclosure>
      <Disclosure id="measurement" title="Evidence and measurement" summary="Weekly figures, source definitions and separate attribution" icon={BarChart3} autoOpen={focus==='measurement'}><Measurement/></Disclosure>
      <Disclosure id="approvals" title="Proposed experiments and approvals" summary="Prioritized implementation tasks · nothing launched or sent" icon={FileCheck2} autoOpen={focus==='approvals'}><div className="mdemo-detail-pad"><h3>Implementation backlog</h3><div className="mdemo-approval-grid">{approvals.map(task=><article key={task.platform}><span>Priority {task.priority} · {task.platform}</span><h4>Proposed action</h4><p>{task.action}</p><h4>Supporting evidence</h4><p>{task.evidence}</p><h4>Expected learning</h4><p>{task.learning}</p><h4>Approval needed</h4><p>{task.approval}</p></article>)}</div></div></Disclosure>
    </section>

    <footer className="mdemo-result-actions"><button type="button" className="mdemo-button-primary" onClick={onWatch}><Play size={15}/>Watch how AURA worked</button><button type="button" className="mdemo-button" onClick={download}><Download size={15}/>Download draft pack</button><button type="button" className="mdemo-text-button" onClick={onStart}>Start from the request<ArrowRight size={14}/></button></footer>
  </div>;
}
