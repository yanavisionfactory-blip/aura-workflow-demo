import { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronRight, Circle, ClipboardCheck, FileText, Layers3, LoaderCircle, Pause, Play, RotateCcw, ShieldCheck, Sparkles, X } from 'lucide-react';
import { BRIEF, TOOLS, executeCommerceSimulation } from '../../lib/commerceSimulation.mjs';
import { Results, ReviewCopy, ToolIcon } from './Results';
import { SCENES, initialScene, sceneUrl } from './walkthrough.mjs';
import ToolWorkspace from './ToolWorkspace';
import { readToolRoute } from './toolNavigation.mjs';
import './commerce.css';
export { Results } from './Results';
const ORDER = ['seller', 'google', 'meta', 'amazon'];
const TASK = 'Prepare a weekly marketing action package for one Unstoprev e-commerce client. Review the Everyday Travel Mug across Google Ads, Meta Ads Manager, Amazon Ads and Amazon Seller Central. Compare the last two complete weeks, check inventory first, and prepare three advertising tests, consistent product copy and a prioritized approval checklist. Keep every change ready for account-manager review.';
const descriptions = {
  seller: 'Check listing, sessions, conversion, total ASIN sales and available inventory first.',
  google: 'Compare search terms, ad performance, spend, clicks, purchase credits and cost per conversion.',
  meta: 'Compare Facebook and Instagram creative, spending, link clicks, purchases and acquisition cost.',
  amazon: 'Compare advertised-product and search-term spend, attributed ASIN sales and ACoS.',
};
let packetPromise;
const prepare = () => packetPromise ||= executeCommerceSimulation('low');
function Brand() { return <span className="ad-brand"><span className="ad-brand-icon"><Sparkles size={18}/></span>AURA</span>; }

function Brief({ onNext }) {
  return <section className="ad-brief ad-enter">
    <div className="ad-orb"><Sparkles size={30}/></div><span className="ad-eyebrow">YOUR AGENCY. FOUR TOOLS. ONE WORKFLOW.</span>
    <h1>What would you like to get done?</h1><p className="ad-intro">From a weekly marketing review to the next round of tests.<br/>Tell AURA the outcome. Review the plan. Stay in control.</p>
    <div className="ad-composer"><label htmlFor="agency-task">Prepared agency demo request</label><textarea id="agency-task" readOnly value={TASK} rows={6}/><div className="ad-composer-bottom"><span><FileText size={14}/>Product brief + 4 simulated reports</span><button className="ad-gradient" onClick={onNext}>Build workflow <ArrowRight size={15}/></button></div></div>
    <div className="ad-connected">{ORDER.map(key => <span key={key}><ToolIcon tool={key}/>{TOOLS[key]}<Check size={12}/></span>)}</div>
    <p className="ad-small ad-centered">Harbor &amp; Field · Everyday Travel Mug · Fictional client scenario<br/>Simulated data throughout. No live accounts or advertising changes.</p>
  </section>;
}
function Plan({ onNext, onBack }) {
  return <section className="ad-stage ad-enter"><span className="ad-eyebrow">WORKFLOW PLAN</span><h1>Here’s how I’ll prepare your review</h1><p className="ad-intro">One product, two complete weeks, four source reports. Every recommendation stays linked to its evidence.</p>
    <div className="ad-context"><span><Layers3 size={14}/>Everyday Travel Mug</span><span>Oct 12–18 vs Oct 5–11, 2026</span><span>USD · America/Chicago</span></div>
    <div className="ad-plan">{ORDER.map((key, i) => <details key={key} className="ad-plan-step"><summary><span className="ad-step-index">{i + 1}</span><ToolIcon tool={key}/><span><strong>{TOOLS[key]}</strong><small>{descriptions[key]}</small></span><span className="ad-read">Read</span><ChevronRight size={15}/></summary><div className="ad-plan-detail">{key === 'seller' ? 'Read the ASIN business report and dated inventory/listing snapshot. Exclude reserved stock and unreceived inbound from available inventory.' : 'Read both complete weeks. Preserve this platform’s attribution definition. Keep its purchase and sales totals separate.'}<p>Output: {key === 'seller' ? 'product readiness and promotion hold' : 'weekly comparison, source evidence and one proposed test'}.</p></div></details>)}<div className="ad-plan-step ad-draft-step"><span className="ad-step-index">5</span><ClipboardCheck size={19}/><span><strong>Prepare the action package</strong><small>Three tests, channel copy and a prioritized approval checklist.</small></span><span className="ad-read">Draft</span></div></div>
    <div className="ad-scope"><ShieldCheck size={17}/><span>Review only. No publishing, launches, budget changes or inventory edits.</span></div><div className="ad-stage-actions"><button onClick={onBack}><ArrowLeft size={14}/>Back</button><button className="ad-gradient" onClick={onNext}>Review proposed output <ArrowRight size={14}/></button></div>
  </section>;
}
function Review({ packet, onNext, onBack }) {
  const [copyOpen, setCopyOpen] = useState(false);
  return <section className="ad-stage ad-enter"><span className="ad-eyebrow">REVIEW BEFORE RUNNING</span><h1>You approve the scope. AURA does the prep.</h1><p className="ad-intro">A prepared example of findings and drafts for your account manager.</p>
    <div className="ad-product"><div className="ad-mug" aria-hidden="true"><span>H&amp;F</span></div><div><span className="ad-small">HARBOR &amp; FIELD · FICTIONAL CLIENT</span><h2>Everyday Travel Mug</h2><p>16 oz · Stainless steel · Fitted lid · Hand-wash</p><span className="ad-tag">{BRIEF.asin} · simulated ASIN</span></div></div>
    <div className="ad-warning"><ShieldCheck size={18}/><div><strong>Inventory check comes first</strong><p>30 available units ≈ 0.70 days of cover. Hold additional Amazon promotion until stock is cleared. Website stock pool is unconfirmed.</p></div></div>
    <div className="ad-review-message"><span className="ad-eyebrow">ONE CONSISTENT PRODUCT MESSAGE</span><h2>“{packet.copy.message}”</h2><p>Uses supplied scenario facts. The website-only offer is excluded from the shared message.</p></div>
    <div className="ad-mini-tests">{packet.tests.map(test => <div key={test.id}><ToolIcon tool={test.source}/><span><strong>{test.title}</strong><small>{test.learning}</small></span><span className="ad-tag">Draft</span></div>)}</div>
    <button className="ad-text-button" onClick={() => setCopyOpen(!copyOpen)} aria-expanded={copyOpen}><FileText size={15}/>{copyOpen ? 'Hide' : 'Preview'} channel copy <ChevronRight size={14}/></button>{copyOpen && <ReviewCopy packet={packet}/>}
    <div className="ad-scope"><ShieldCheck size={17}/><span>This approval runs the demo’s read-only simulation. Client approval remains required before implementing any recommendation.</span></div><div className="ad-stage-actions"><button onClick={onBack}><ArrowLeft size={14}/>Back to plan</button><button className="ad-gradient" onClick={onNext}><Play size={14}/>Approve demo run</button></div>
  </section>;
}
function Execution({ onNext }) {
  const [count, setCount] = useState(0);
  useEffect(() => { const timer = setInterval(() => setCount(n => Math.min(n + 1, 5)), 950); return () => clearInterval(timer); }, []);
  return <section className="ad-stage ad-execution ad-enter"><div className="ad-orb">{count === 5 ? <CheckCircle2 size={30}/> : <Sparkles size={30}/>}</div><span className="ad-eyebrow">SIMULATED WORKFLOW PLAYBACK</span><h1>{count === 5 ? 'Your review is ready' : 'Preparing your weekly action package'}</h1><p className="ad-intro">Four simulated reports reviewed. All changes remain drafts.</p><div className="ad-progress-track"><span style={{ width: `${count * 20}%` }}/></div><div className="ad-execution-list">{[...ORDER, 'package'].map((key, i) => <div key={key} className={count > i ? 'is-complete' : count === i ? 'is-current' : ''}><span className="ad-execution-icon">{count > i ? <CheckCircle2 size={19}/> : count === i ? <LoaderCircle className="ad-spin" size={19}/> : <Circle size={19}/>}</span><span><strong>{key === 'package' ? 'Validate evidence and assemble review drafts' : TOOLS[key]}</strong><small>{count > i ? key === 'seller' ? 'Inventory hold flagged · listing issues retained' : key === 'package' ? 'Three tests + copy + approval checklist prepared' : 'Weekly comparison and evidence ready' : key === 'package' ? 'Draft only · no delivery or publication' : 'Local simulated source review'}</small></span>{count > i && <span className="ad-tag">Reviewed</span>}</div>)}</div><p className="ad-small ad-centered">Prepared playback of local report processing. Vendor APIs and models are not called.</p><button className="ad-gradient" disabled={count < 5} onClick={onNext}>View results <ArrowRight size={15}/></button></section>;
}
export default function App() {
  const [scene, setScene] = useState(() => initialScene(typeof window === 'undefined' ? '' : window.location.search));
  const [packet, setPacket] = useState(null), [error, setError] = useState('');
  const [guide, setGuide] = useState(() => typeof window === 'undefined' || new URLSearchParams(window.location.search).get('screen') !== 'results');
  const [playing, setPlaying] = useState(false);
  useEffect(() => { let active = true; prepare().then(value => { if (active) setPacket(value); }).catch(cause => { if (active) setError(cause.message); }); return () => { active = false; }; }, []);
  useEffect(() => { const onPop = () => { setScene(initialScene(window.location.search)); setPlaying(false); }; window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop); }, []);
  const navigate = (next, manual = true) => { const value = Math.max(0, Math.min(4, next)); setScene(value); if (manual || value === 4) setPlaying(false); window.history.pushState({}, '', sceneUrl(value, window.location.href)); window.scrollTo({ top: 0, behavior: 'instant' }); };
  useEffect(() => { if (!playing || !packet || scene === 4) return; const timer = setTimeout(() => navigate(scene + 1, false), scene === 3 ? 6500 : 8500); return () => clearTimeout(timer); }, [playing, scene, packet]);
  const restart = () => { setGuide(true); navigate(0); };
  const toolRoute = typeof window === 'undefined' ? null : readToolRoute(window.location.search);
  if (toolRoute && packet) return <ToolWorkspace packet={packet} route={toolRoute}/>;
  return <div className={`agency-demo ${guide ? 'with-guide' : ''}`}><header className="ad-topbar"><button className="ad-brand-button" onClick={restart} aria-label="AURA demo home"><Brand/></button><span className="ad-breadcrumb">Unstoprev <ChevronRight size={12}/>Weekly marketing</span><div className="ad-top-right"><span className="ad-demo-badge"><span/>Agency walkthrough · Simulated</span>{!guide && <button className="ad-guide-toggle" onClick={() => setGuide(true)}><Play size={12}/>Walkthrough</button>}</div></header><main className={scene === 4 ? 'ad-main ad-results-main' : 'ad-main'}>{error ? <div role="alert" className="ad-warning">The example could not load: {error}<button onClick={() => window.location.reload()}>Reload demo</button></div> : !packet ? <div className="ad-loading" role="status"><LoaderCircle className="ad-spin"/>Preparing the simulated reports…</div> : scene === 0 ? <Brief onNext={() => navigate(1)}/> : scene === 1 ? <Plan onNext={() => navigate(2)} onBack={() => navigate(0)}/> : scene === 2 ? <Review packet={packet} onNext={() => navigate(3)} onBack={() => navigate(1)}/> : scene === 3 ? <Execution onNext={() => navigate(4)}/> : <Results packet={packet} onNew={restart} onReplay={() => { setGuide(true); navigate(3); }}/>}</main>
    {guide && <aside className="ad-tour" aria-label="Agency walkthrough controls"><div className="ad-tour-progress">{SCENES.map((item, i) => <button key={item.title} title={item.title} aria-label={`Step ${i + 1}: ${item.title}`} aria-current={scene === i ? 'step' : undefined} onClick={() => navigate(i)} className={i <= scene ? 'is-active' : ''}/>)}</div><div className="ad-tour-body"><span className="ad-tour-number">{scene + 1}<small>/ 5</small></span><div className="ad-tour-caption" aria-live="polite"><strong>{SCENES[scene].title}</strong><p>{SCENES[scene].caption}</p></div><div className="ad-tour-buttons"><button disabled={scene === 0} onClick={() => navigate(scene - 1)} aria-label="Previous walkthrough step"><ArrowLeft size={16}/></button><button onClick={() => { if (scene === 4) navigate(0, false); setPlaying(v => !v); }} aria-label={playing ? 'Pause walkthrough' : 'Play walkthrough'}>{playing ? <Pause size={16}/> : <Play size={16}/>}</button><button className="ad-gradient" onClick={() => scene === 4 ? restart() : navigate(scene + 1)}>{scene === 4 ? <RotateCcw size={14}/> : null}{scene === 4 ? 'Replay' : 'Next'}{scene !== 4 && <ArrowRight size={14}/>}</button><button className="ad-hide-guide" onClick={() => { setGuide(false); setPlaying(false); }} aria-label="Hide walkthrough guide"><X size={16}/></button></div></div></aside>}
  </div>;
}
