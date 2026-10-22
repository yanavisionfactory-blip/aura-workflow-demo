import {useEffect,useState} from 'react';
import {useLocation,useNavigate} from 'react-router-dom';
import {ArrowLeft,ArrowRight,Check,CheckCircle2,Pause,Play,RotateCcw,ShieldCheck,Sparkles,X} from 'lucide-react';
import ExecutionView from '@/components/aura/ExecutionView';
import MarketingDemoResults from './MarketingDemoResults';
import {brief,tools} from './data.mjs';
import {originalPrompt,workflowSteps,tour,validPhases,sceneFromSearch,executionSteps} from './scenario.mjs';

function Request({onPlan}) {
  const [prompt,setPrompt]=useState(originalPrompt);
  const [error,setError]=useState('');
  return <section className="mdemo-request"><div className="mdemo-request-heading"><Sparkles size={28}/><span>ONE BUSINESS OUTCOME · FOUR TOOLS</span><h1>What would you like AURA to do?</h1><p>Describe the campaign once. Let AURA coordinate the work.</p></div><div className="mdemo-prompt-box"><textarea aria-label="Prepared marketing request" value={prompt} onChange={event=>setPrompt(event.target.value)} rows={10}/><div><span>Prepared demo task</span><button type="button" className="mdemo-button-primary" onClick={()=>{if(prompt.trim()!==originalPrompt.trim()){setError('This separate demo follows the prepared marketing task. Restore it to continue.');return;}onPlan();}}>Create plan<ArrowRight size={15}/></button></div></div><div className="mdemo-tool-chips">{tools.map(tool=><span key={tool.key}><Check size={12}/>{tool.name}</span>)}</div>{error&&<p className="mdemo-input-error" role="alert">{error}<button type="button" onClick={()=>{setPrompt(originalPrompt);setError('');}}>Restore prepared task</button></p>}</section>;
}

function Plan({onReview,onBack}) {
  return <section className="mdemo-plan"><span className="mdemo-eyebrow">AURA WORKFLOW PLAN</span><h1>One campaign from first visit to next purchase</h1><p className="mdemo-muted">AURA coordinates the tools around one brief, approved scenario offers and clear audience boundaries.</p><ol className="mdemo-plan-steps">{workflowSteps.map((step,index)=><li key={step.tool}><span className="mdemo-step-number">{index+1}</span><div><span>{step.tool}</span><h2>{step.title}</h2><p>{step.action}</p><small>{step.output}</small></div><span className="mdemo-draft-chip">Draft only</span></li>)}</ol><div className="mdemo-plan-actions"><button type="button" className="mdemo-button" onClick={onBack}><ArrowLeft size={14}/>Edit request</button><button type="button" className="mdemo-button-primary" onClick={onReview}>Review inputs<ArrowRight size={14}/></button></div></section>;
}

function Review({onRun,onBack}) {
  return <section className="mdemo-review"><span className="mdemo-eyebrow">REVIEW BEFORE PLAYBACK</span><h1>One fictional client, one consistent campaign</h1><p className="mdemo-muted">These are prepared scenario inputs. Starting the walkthrough does not approve or execute a real campaign.</p><div className="mdemo-review-grid"><article><ShieldCheck size={21}/><h2>Client and tools</h2><p>{brief.client} is fictional. Every tool screen uses the same synthetic scenario, with no live accounts or sign-in.</p><div className="mdemo-tool-chips">{tools.map(tool=><span key={tool.key}>{tool.name}</span>)}</div></article><article><CheckCircle2 size={21}/><h2>Shared objective and offer</h2><p>{brief.objective}</p><p>{brief.offer}</p></article><article><CheckCircle2 size={21}/><h2>Lifecycle boundaries</h2><p>{brief.audience_ownership}</p></article><article><ShieldCheck size={21}/><h2>Reporting and approvals</h2><p>Compare October 12–18 with October 5–11, 2026. Keep Meta Ads and Klaviyo attribution separate. All proposed implementation tasks need account-manager review.</p></article></div><div className="mdemo-plan-actions"><button type="button" className="mdemo-button" onClick={onBack}><ArrowLeft size={14}/>Back to plan</button><button type="button" className="mdemo-button-primary" onClick={onRun}><Play size={14}/>Play prepared workflow</button></div></section>;
}

export default function ShowcaseApp() {
  const location=useLocation();
  const navigate=useNavigate();
  const params=new URLSearchParams(location.search);
  const scene=sceneFromSearch(location.search);
  const current=scene>=0?tour[scene]:null;
  const auto=params.get('tour')==='1'||params.get('play')==='1';
  const requested=params.get('screen')||'results';
  const phase=current?.phase||(validPhases.has(requested)?requested:'results');
  const requestedFocus=current?.focus||params.get('focus');
  const focus=['google','mailchimp','klaviyo','coordination','measurement','approvals'].includes(requestedFocus)?requestedFocus:null;
  const [progress,setProgress]=useState(0);
  const move=screen=>navigate(`?screen=${screen}`);
  const start=()=>navigate('?tour=1');
  const goScene=(index,play=false)=>navigate(`?scene=${index}${play?'&play=1':''}`);

  useEffect(()=>{
    if(!current||!auto)return undefined;
    const timer=window.setTimeout(()=>{if(scene<tour.length-1)navigate(`?scene=${scene+1}&play=1`);else navigate(`?scene=${scene}`,{replace:true});},current.seconds*1000);
    return()=>window.clearTimeout(timer);
  },[auto,current,scene,navigate]);
  useEffect(()=>{
    if(phase!=='execution')return undefined;
    setProgress(0);let complete=0;
    const timer=window.setInterval(()=>{complete++;setProgress(complete);if(complete>=workflowSteps.length){window.clearInterval(timer);if(!current)navigate('?screen=results');}},1000);
    return()=>window.clearInterval(timer);
  },[phase,current,navigate]);
  useEffect(()=>{
    const timer=window.setTimeout(()=>{if(phase==='results'&&focus)document.getElementById(`demo-${focus}`)?.scrollIntoView({block:'start',behavior:'instant'});else window.scrollTo({top:0,behavior:'instant'});},80);
    return()=>window.clearTimeout(timer);
  },[phase,focus,scene,location.key]);

  return <div className={`marketing-demo ${current?'mdemo-touring':''}`}>
    <header className="mdemo-topbar"><button type="button" className="mdemo-logo" onClick={()=>move('results')} aria-label="AURA main outcome"><span><Sparkles size={21}/></span>AURA<small>DEMO</small></button><nav aria-label="Demo navigation"><button type="button" onClick={()=>move('results')}>Main outcome</button><button type="button" onClick={start}><Play size={13}/>Watch how AURA worked</button><button type="button" onClick={()=>move('input')}>Start from request</button><button type="button" aria-label="Restart demo" onClick={()=>move('results')}><RotateCcw size={14}/></button></nav></header>
    <div className="mdemo-demo-strip"><span><strong>SEPARATE PUBLIC DEMO</strong> · Maple & Ember Coffee · all four tools simulated · no sign-in</span><span>Drafts only · nothing launched or sent</span></div>
    <main className={`mdemo-main mdemo-phase-${phase}`}>
      {phase==='results'&&<MarketingDemoResults key={`${location.key}-${scene}-${focus||'main'}`} focus={focus} onWatch={start} onStart={()=>move('input')}/>}
      {phase==='input'&&<Request onPlan={()=>move('plan')}/>}
      {phase==='plan'&&<Plan onReview={()=>move('review')} onBack={()=>move('input')}/>}
      {phase==='review'&&<Review onRun={()=>move('execution')} onBack={()=>move('plan')}/>}
      {phase==='execution'&&<section className="mdemo-playback"><p className="mdemo-note">Prepared local playback · synthetic tool outputs · no provider API calls or external writes.</p><ExecutionView steps={executionSteps(progress)} currentStepIndex={progress} demo/><button type="button" className="mdemo-button" onClick={()=>move('results')}>Skip to the main outcome<ArrowRight size={14}/></button></section>}
    </main>
    <footer className="mdemo-page-footer"><span>AURA coordinates. The tools own their outputs.</span><span>Prepared public demonstration · fictional client</span></footer>
    {current&&<aside className="mdemo-tour" aria-label="Guided marketing walkthrough"><div><span>{scene+1} / {tour.length} · {current.title}</span><button type="button" aria-label="Close walkthrough" onClick={()=>move('results')}><X size={15}/></button></div><p>{current.caption}</p><nav><button type="button" disabled={scene===0} onClick={()=>goScene(Math.max(0,scene-1))}><ArrowLeft size={13}/>Back</button><div className="mdemo-tour-dots" aria-label="Walkthrough scenes">{tour.map((item,index)=><button type="button" key={item.title} aria-label={`Scene ${index+1}: ${item.title}`} aria-current={scene===index?'step':undefined} onClick={()=>goScene(index)}/>)}</div><button type="button" onClick={()=>goScene(scene,!auto)}>{auto?<Pause size={13}/>:<Play size={13}/>} {auto?'Pause':'Play'}</button><button type="button" disabled={scene===tour.length-1} onClick={()=>goScene(Math.min(tour.length-1,scene+1))}>Next<ArrowRight size={13}/></button></nav></aside>}
  </div>;
}
