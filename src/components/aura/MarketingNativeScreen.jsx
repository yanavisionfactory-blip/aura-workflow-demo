import { useState } from 'react';
import { BarChart3, CalendarDays, Check, ChevronDown, Clock3, FileText, FlaskConical, GitBranch, Image, LayoutDashboard, Mail, MoreHorizontal, MousePointer2, Search, Settings, ShieldCheck, Users } from 'lucide-react';
import { marketingPeriodRows, nativeDiscoveryRows, sourcePurchaseCpa } from '@/lib/marketingScreenData.mjs';
import { EvidenceValue } from './ToolEvidence';
import './marketing-native-screens.css';

const currency = value => value == null ? '—' : new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(value);
const number = value => value == null ? '—' : Number(value).toLocaleString('en-US');
const toolNames = {meta:'Meta Ads',google:'Google Ads',mailchimp:'Mailchimp',klaviyo:'Klaviyo'};
const menus = {
  meta:[['campaigns','Campaigns',BarChart3],['ads','Ad creative',Image],['evidence','Evidence',FileText]],
  google:[['campaigns','Campaigns',BarChart3],['ads','Ad preview',MousePointer2],['evidence','Evidence',FileText]],
  mailchimp:[['email','Email builder',Mail],['audience','Audience',Users],['evidence','Evidence',FileText]],
  klaviyo:[['flows','Flow builder',GitBranch],['analytics','Analytics',BarChart3],['email','Email preview',Mail],['evidence','Evidence',FileText]],
};

function Brand({tool}) {
  if(tool==='meta') return <span className="mts-brand mts-brand-meta"><span aria-hidden="true">∞</span>Meta</span>;
  if(tool==='google') return <span className="mts-brand"><svg viewBox="0 0 24 24" width="25" height="25" aria-hidden="true"><path d="M10 4a4 4 0 0 1 7 0l6 11a4 4 0 0 1-7 4Z" fill="#4285f4"/><path d="M10 4a4 4 0 0 1 7 4L9 20a4 4 0 0 1-7-4Z" fill="#fbbc04"/><circle cx="5.5" cy="18" r="4" fill="#34a853"/></svg>Google Ads</span>;
  if(tool==='mailchimp') return <span className="mts-brand mts-brand-mailchimp"><span aria-hidden="true" className="mts-mailchimp-mark">m</span>mailchimp</span>;
  return <span className="mts-brand mts-brand-klaviyo">klaviyo<span aria-hidden="true">›</span></span>;
}

function Field({label,value,multiline=false}) {
  return <label className="mts-field"><span>{label}</span>{multiline?<textarea readOnly rows={4} value={value || 'Pending approval'}/>:<input readOnly value={value || 'Pending approval'}/>}</label>;
}

function DraftPicker({drafts,index,onChange,label='Draft variation'}) {
  return <label className="mts-select"><span>{label}</span><select value={index} onChange={event=>onChange(Number(event.target.value))}>{drafts.map((draft,i)=><option key={draft.id} value={i}>{draft.title}</option>)}</select></label>;
}

function MetricCards({items}) {
  return <div className="mts-metrics">{items.map(([label,value,previous])=><div key={label}><span>{label}</span><strong>{value}</strong>{previous!=null && <small>Previous week: {previous}</small>}</div>)}</div>;
}

function PeriodPicker({packet,value,onChange}) {
  return <label className="mts-date"><CalendarDays size={14}/><span className="mts-sr-only">Reporting period</span><select aria-label="Reporting period" value={value} onChange={event=>onChange(event.target.value)}>{['current','previous'].map(period=><option key={period} value={period}>{period==='current'?'Latest complete week':'Previous week'} · {packet.periods[period].from} – {packet.periods[period].to}</option>)}</select></label>;
}

function MetaCampaigns({packet,onOpenAds}) {
  const [period,setPeriod] = useState('current');
  const [search,setSearch] = useState('');
  const rows=marketingPeriodRows(packet,period,search);
  const total=packet.comparison[period];
  const previous=period==='current'?packet.comparison.previous:null;
  return <>
    <div className="mts-page-heading"><div><h3>Campaigns</h3><p>Maple & Ember Coffee · synthetic account</p></div><PeriodPicker packet={packet} value={period} onChange={setPeriod}/></div>
    <MetricCards items={[
      ['Amount spent',currency(total.spend),previous&&currency(previous.spend)],['Website purchases',number(total.purchases),previous&&number(previous.purchases)],
      ['Cost per purchase',currency(total.purchase_cpa),previous&&currency(previous.purchase_cpa)],['Purchase conversion value',currency(total.revenue),previous&&currency(previous.revenue)],
    ]}/>
    <div className="mts-meta-levels"><strong><BarChart3 size={15}/>Campaigns <span>{rows.length}</span></strong><span>Ad sets <small>Not supplied</small></span><button type="button" onClick={onOpenAds}>Ads <small>2 proposals</small></button></div>
    <div className="mts-toolbar"><label className="mts-search"><Search size={15}/><input aria-label="Search Meta campaigns" placeholder="Search campaigns" value={search} onChange={event=>setSearch(event.target.value)}/></label><button type="button" className="mts-button mts-meta-button" onClick={onOpenAds}>View creative proposals</button><span className="mts-toolbar-label">Columns: Performance <ChevronDown size={13}/></span></div>
    <div className="mts-table-wrap"><table className="mts-table"><caption>Simulated weekly performance · campaign breakdown</caption><thead><tr>{['Campaign','Delivery','Amount spent','Purchases','Cost per purchase','Link clicks','Frequency'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{rows.map(row=><tr key={row.id}><th><span className="mts-campaign-name">{row.campaign}</span><small>{row.id}</small></th><td><span className="mts-neutral-status">Synthetic row</span></td><td>{currency(row.spend)}</td><td>{number(row.purchases)}</td><td>{currency(sourcePurchaseCpa(row))}</td><td>{number(row.link_clicks)}</td><td>{Number(row.frequency).toFixed(2)}</td></tr>)}{!rows.length && <tr><td colSpan={7}>No source rows match this search.</td></tr>}</tbody></table></div>
    <div className="mts-source-note"><strong>{packet.timezone} · {packet.currency}</strong><span>{packet.attribution}</span></div>
    <section className="mts-insight"><h4>Recommended creative test</h4>{packet.findings.map(item=><p key={item.finding}>{item.finding}<small>Source: {item.evidence.join(' · ')}</small></p>)}</section>
  </>;
}

function MetaAds({packet}) {
  const [index,setIndex] = useState(0);
  const draft=packet.drafts[index];
  return <><div className="mts-page-heading"><div><h3>Ad creative</h3><p>Proposed creative; not saved in Meta</p></div><span className="mts-draft-badge">Unsaved proposal</span></div><DraftPicker drafts={packet.drafts} index={index} onChange={setIndex}/><div className="mts-editor-columns"><div className="mts-editor-fields"><h4>Ad setup</h4><Field label="Ad name" value={draft.title}/><Field label="Primary text" value={draft.primary_text} multiline/><Field label="Headline" value={draft.headline}/><Field label="Call to action" value={draft.cta}/><Field label="Website URL · placeholder" value={draft.url}/><div className="mts-info-box"><strong>Creative concept</strong><p>{draft.concept}</p></div><div className="mts-variation-list" aria-label="Available creative proposals">{packet.drafts.map((item,i)=><button type="button" key={item.id} aria-pressed={i===index} onClick={()=>setIndex(i)}><Image size={16}/><span>{item.title}<small>{item.status}</small></span><ChevronDown size={13}/></button>)}</div></div><div className="mts-preview-column"><span className="mts-preview-caption">Ad preview · Facebook Feed</span><article className="mts-facebook-post"><header><span className="mts-coffee-avatar">M&E</span><div><strong>Maple & Ember Coffee</strong><small>Sponsored · preview</small></div><MoreHorizontal size={18}/></header><p>{draft.primary_text}</p><div className="mts-creative-placeholder"><Image size={32}/><strong>{draft.title}</strong><span>Creative asset pending approval</span></div><footer><div><small>MAPLE-EMBER.EXAMPLE</small><strong>{draft.headline}</strong></div><span>{draft.cta}</span></footer><div className="mts-post-reactions">Like <span>Comment</span><span>Share</span></div></article><p className="mts-fineprint">Concept preview only. Image, video and placement fit require approval.</p></div></div><Experiment packet={packet}/></>;
}

function EmailPreview({draft,tool}) {
  return <div className="mts-email-preview"><div className="mts-email-envelope"><strong>Subject: {draft.subject_options?.[0]}</strong><span>{draft.preheader}</span><small>From: client sender awaiting approval</small></div><article className={`mts-email-paper ${tool==='mailchimp'?'mts-email-paper-mailchimp':''}`}><div className="mts-email-wordmark">MAPLE & EMBER <span>COFFEE</span></div><div className="mts-email-rule"/><h4>{draft.title==='Abandoned checkout'?'Your next morning brew is waiting':draft.title==='Repeat-purchase replenishment'?'A fresh start for your next cup':'Meet your morning coffee'}</h4><p>{draft.body}</p><span className="mts-email-cta">{draft.cta}</span><div className="mts-email-footer">Maple & Ember Coffee · fictional scenario<br/>Approved sender, postal address, unsubscribe and preferences links required.</div></article></div>;
}

function KlaviyoFlow({packet,onOpenEmail}) {
  const [index,setIndex] = useState(0);
  const draft=packet.drafts[index];
  return <><div className="mts-page-heading"><div><h3>{draft.title}</h3><p>Flows / Meet your morning coffee</p></div><span className="mts-draft-badge">DRAFT · proposal only</span></div><DraftPicker drafts={packet.drafts} index={index} onChange={setIndex} label="Flow proposal"/><div className="mts-flow-layout"><aside className="mts-flow-settings"><h4>Flow details</h4><span className="mts-tiny-label">Trigger & timing</span><p>{draft.trigger}</p><span className="mts-tiny-label">Flow filters</span><p>{draft.eligibility}</p><span className="mts-tiny-label">Status</span><p>Simulated draft; no native flow or message created</p><button type="button" className="mts-button" onClick={()=>onOpenEmail(index)}>Preview email</button></aside><div className="mts-flow-canvas" aria-label="Proposed flow canvas"><div className="mts-flow-node mts-trigger-node"><span className="mts-node-icon"><GitBranch size={18}/></span><small>TRIGGER</small><strong>{index===0?'Started Checkout':'Fulfilled Order'}</strong><p>Simulated event · verification required</p></div><span className="mts-flow-line"/><div className="mts-flow-delay"><Clock3 size={15}/>{index===0?'Wait 4 hours':'Wait 28 days'}</div><span className="mts-flow-line"/><button type="button" className="mts-flow-node mts-message-node" onClick={()=>onOpenEmail(index)}><span className="mts-node-icon"><Mail size={18}/></span><small>EMAIL · DRAFT</small><strong>{draft.title}</strong><p>{draft.subject_options[0]}</p><span className="mts-node-action">Preview email →</span></button><span className="mts-flow-line"/><span className="mts-flow-end">End</span><p className="mts-flow-exit"><ShieldCheck size={14}/>Exit on purchase or suppression. Eligibility rechecked before sending.</p></div></div><div className="mts-info-box"><strong>Suppression and channel ownership</strong><p>{draft.suppression}</p></div><Experiment packet={packet}/></>;
}

function KlaviyoAnalytics({packet}) {
  const [period,setPeriod]=useState('current');
  const total=packet.comparison[period];
  return <><div className="mts-page-heading"><div><h3>Flow performance</h3><p>Simulated weekly performance</p></div><PeriodPicker packet={packet} value={period} onChange={setPeriod}/></div><MetricCards items={[
    ['Attributed revenue',currency(total.revenue)],['Attributed orders',number(total.orders)],['Clicks',number(total.clicks)],['Unsubscribes',number(total.unsubscribes)],
  ]}/><div className="mts-table-wrap"><table className="mts-table"><caption>Flow message results · synthetic source rows</caption><thead><tr>{['Flow message','Delivered','Clicks','Orders','Revenue','Unsubscribes'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{marketingPeriodRows(packet,period).map(row=><tr key={row.id}><th>{row.campaign}<small>{row.id}</small></th><td>{number(row.delivered)}</td><td>{number(row.clicks)}</td><td>{number(row.orders)}</td><td>{currency(row.revenue)}</td><td>{number(row.unsubscribes)}</td></tr>)}</tbody></table></div><div className="mts-source-note"><strong>{packet.timezone} · {packet.currency}</strong><span>{packet.attribution}</span></div>{packet.findings.map(item=><div className="mts-insight" key={item.finding}><p>{item.finding}<small>Source: {item.evidence.join(' · ')}</small></p></div>)}</>;
}

function EmailEditor({drafts,tool,initialIndex=0}) {
  const [index,setIndex]=useState(initialIndex);
  const draft=drafts[index];
  if(!draft) return <div className="mts-empty-state">No email proposal is available.</div>;
  return <><div className="mts-page-heading"><div><h3>{tool==='mailchimp'?'Email campaign':'Email content'}</h3><p>{tool==='mailchimp'?'Proposed invitation · client audience not selected':'Recovery and repeat-purchase emails · simulated draft'}</p></div><span className="mts-draft-badge">Draft preview · unsaved</span></div><DraftPicker drafts={drafts} index={index} onChange={setIndex}/><div className="mts-editor-columns"><div className="mts-editor-fields"><h4>{tool==='mailchimp'?'Campaign checklist':'Message details'}</h4>{tool==='mailchimp' && <><Field label="To" value="Permissioned non-purchasers · awaiting verified client audience"/><Field label="From" value="Sender awaiting client approval"/></>}<Field label="Subject line A" value={draft.subject_options?.[0]}/><Field label="Subject line B" value={draft.subject_options?.[1]}/><Field label="Preview text" value={draft.preheader}/><Field label="Email body" value={draft.body} multiline/><Field label="Call to action" value={draft.cta}/><Field label="Tracked destination · placeholder" value={draft.url}/>{['trigger','eligibility','suppression'].map(key=>draft[key] && <div className="mts-info-box" key={key}><strong>{key}</strong><p>{draft[key]}</p></div>)}</div><div className="mts-preview-column"><span className="mts-preview-caption">Desktop email preview</span><EmailPreview draft={draft} tool={tool}/></div></div></>;
}

function GoogleAds({brief}) {
  const [index,setIndex]=useState(0);
  const draft=brief.google_drafts[index];
  return <><div className="mts-page-heading"><div><h3>Responsive search ad</h3><p>Proposed assets · unsaved</p></div><span className="mts-draft-badge">Draft proposal</span></div><DraftPicker drafts={brief.google_drafts} index={index} onChange={setIndex}/><div className="mts-editor-columns"><div className="mts-editor-fields"><h4>Ad text</h4><Field label="Final URL · placeholder" value={draft.url}/>{draft.headlines.map((headline,i)=><Field key={headline} label={`Headline ${i+1} · ${headline.length}/30`} value={headline}/>)}{draft.descriptions.map((description,i)=><Field key={description} label={`Description ${i+1} · ${description.length}/90`} value={description} multiline/>)}<div className="mts-info-box"><strong>Account selection required</strong><p>{brief.native_proposals_note}</p></div></div><div className="mts-preview-column"><span className="mts-preview-caption">Search ad preview · example combination</span><article className="mts-google-ad"><small>Sponsored · preview</small><div className="mts-google-ad-domain"><span>M</span><div><strong>Maple & Ember Coffee</strong><small>maple-ember.example › house-blend</small></div></div><h4>{draft.headlines.join(' | ')}</h4><p>{draft.descriptions.join(' ')}</p></article><p className="mts-fineprint">Proposed copy from the synthetic brief. No ad exists in the connected account. Google may display different asset combinations.</p></div></div></>;
}

function NativeDiscovery({current,demoMode=false}) {
  const rows=nativeDiscoveryRows(current.response,current.key);
  return <><div className="mts-page-heading"><div><h3>{current.key==='google'?'Campaigns':'Audience'}</h3><p>{current.key==='google'?'Available account discovery':'Available audience metadata'}</p></div><span className="mts-neutral-status">{current.label}</span></div><div className="mts-info-box mts-warning"><strong>Account selection required</strong><p>These discovery results do not establish that an account belongs to Maple & Ember Coffee. A verified same-client mapping is required before performance queries.</p></div><div className="mts-table-wrap"><table className="mts-table"><caption>{demoMode?'Synthetic discovery example · fictional account':'Native discovery evidence · not a client match'}</caption><thead><tr>{(current.key==='google'?['Available account','Identifier','Client mapping']:['Available audience','Contacts','Client mapping']).map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={row.id || row.value || i}><th>{current.key==='google'?row.label || row.name || row.value:row.name || 'Unnamed audience'}</th><td>{current.key==='google'?row.value || row.id || 'Not supplied':number(row.stats?.member_count)}</td><td>{demoMode?'Fictional scenario only':'Unverified'}</td></tr>)}{!rows.length && <tr><td colSpan={3}>{current.response?'No recognizable discovery rows in this response. Inspect the source evidence.':'No native response is available. This does not mean zero accounts or audiences.'}</td></tr>}</tbody></table></div><div className="mts-empty-state"><BarChart3 size={27}/><h4>Performance report not loaded</h4><p>Campaign spending, conversions and revenue have not been queried for a verified client.</p></div></>;
}

function Experiment({packet}) {
  return <section className="mts-experiment"><h4>Proposed experiment · {packet.test.platform}</h4><p>{packet.test.action}</p>{packet.test.audience && <p>{packet.test.audience}</p>}<p><strong>Expected learning:</strong> {packet.test.learning}</p><p><strong>Approval needed:</strong> {packet.test.approval}</p></section>;
}

function SourceEvidence({current,packet}) {
  return <div className="mts-evidence"><h3>Source rows and execution receipt</h3><p>{current.label} · Operation: {current.operation}</p>{current.step?.error && <p className="mts-evidence-error">{current.step.error}</p>}{packet?<><p>Simulated weekly performance · {packet.periods.current.from}–{packet.periods.current.to} versus {packet.periods.previous.from}–{packet.periods.previous.to}</p><p>{packet.attribution}</p><EvidenceValue value={packet.comparison}/><EvidenceValue value={packet.rows}/><EvidenceValue value={packet.receipt}/>{packet.routing_checks && <><h4>Simulated audience routing checks</h4><EvidenceValue value={packet.routing_checks}/></>}</>:current.response?<EvidenceValue value={current.response}/>:<p>No native response is saved. This does not mean the platform returned zero rows.</p>}</div>;
}

export default function MarketingNativeScreen({current,packet,brief,initialSection,demoMode=false}) {
  const key=current.key;
  const [section,setSection]=useState(initialSection || {meta:'campaigns',google:'ads',mailchimp:'email',klaviyo:'flows'}[key]);
  const [emailIndex,setEmailIndex]=useState(0);
  const isSimulation=current.mode==='Simulated';
  const tool=toolNames[key];
  const openEmail=index=>{setEmailIndex(index);setSection('email');};
  return <div className={`marketing-tool-screen mts-${key}`} aria-label={`${tool} interface preview`}>
    <div className={`mts-provenance ${isSimulation?'mts-provenance-sim':'mts-provenance-native'}`}>{isSimulation?<FlaskConical size={15}/>:<ShieldCheck size={15}/>}<span><strong>{demoMode?'Prepared public demo · all data is synthetic':isSimulation?'Simulated interface · synthetic data':'Interface imitation · native discovery evidence'}</strong>{demoMode?'Fictional client, accounts and tool outputs. No live provider calls.':isSimulation?'This adapter executed in AURA’s browser; the vendor API was not called.':'This is a preview inside AURA, not a live vendor screen.'} All assets are proposals; no native campaign, flow or message was created.</span></div>
    <div className="mts-app-header"><Brand tool={key}/><div className="mts-account-label">{isSimulation?'Maple & Ember Coffee · simulated account':'Client account not matched'}<ChevronDown size={13}/></div><span className="mts-read-only"><Check size={13}/>Read-only preview</span></div>
    {!isSimulation && <div className="mts-client-warning"><strong>Account selection required · {current.label}</strong><p>{brief.native_limit}</p>{current.step?.error && <p>{current.step.error}</p>}</div>}
    <div className="mts-app-body"><aside className="mts-sidebar"><span className="mts-sidebar-label">{key==='meta'?'Ads Manager':key==='google'?'Workspace':key==='mailchimp'?'Marketing':'Marketing platform'}</span>{menus[key].map(([id,label,Icon])=><button type="button" key={id} className={section===id?'mts-nav-active':''} aria-current={section===id?'page':undefined} onClick={()=>setSection(id)}><Icon size={16}/>{label}</button>)}<div className="mts-sidebar-secondary"><span><LayoutDashboard size={15}/>Overview</span><span><Users size={15}/>Audiences</span><span><Settings size={15}/>Settings</span><small>AURA interface preview</small></div></aside><div className="mts-main">
      {section==='evidence'?<SourceEvidence current={current} packet={isSimulation?packet:null}/>:key==='meta'?(packet?section==='ads'?<MetaAds packet={packet}/>:<MetaCampaigns packet={packet} onOpenAds={()=>setSection('ads')}/>:<div className="mts-empty-state">No successful Meta Ads simulation response is saved.</div>):key==='klaviyo'?(packet?section==='analytics'?<KlaviyoAnalytics packet={packet}/>:section==='email'?<EmailEditor key={emailIndex} drafts={packet.drafts} tool={key} initialIndex={emailIndex}/>:<KlaviyoFlow packet={packet} onOpenEmail={openEmail}/>:<div className="mts-empty-state">No successful Klaviyo simulation response is saved.</div>):key==='google'?(section==='ads'?<GoogleAds brief={brief}/>:<NativeDiscovery current={current} demoMode={demoMode}/>):section==='email'?<EmailEditor drafts={brief.mailchimp_drafts} tool={key}/>:<NativeDiscovery current={current} demoMode={demoMode}/>}
      {section!=='evidence' && <div className="mts-bottom-evidence"><button type="button" onClick={()=>setSection('evidence')}><FileText size={14}/>Source rows and execution receipt</button><span>{isSimulation?'Synthetic results · attribution kept separate':'Discovery only · client matching required'}</span></div>}
    </div></div>
  </div>;
}
