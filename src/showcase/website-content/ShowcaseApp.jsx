import {useEffect,useRef,useState} from 'react';
import {Link,useLocation,useNavigate} from 'react-router-dom';
import {ArrowLeft,ArrowRight,Copy,MessageSquare,Pause,Play,RotateCcw,Video,X} from 'lucide-react';
import WorkspaceShell from '@/components/aura/WorkspaceShell';
import CommandInput from '@/components/aura/CommandInput';
import PreviewView from '@/components/aura/PreviewView';
import ExecutionView from '@/components/aura/ExecutionView';
import WebsiteContentResult from '@/components/aura/WebsiteContentResult';
import SimulatedCMSScreen from '@/components/aura/SimulatedCMSScreen';
import {websiteCMSPreview} from '@/lib/websiteCMSPreview.mjs';
import ShowcasePlan from './ShowcasePlan';
import SourceReview from './SourceReview';
import data from './data.mjs';
import {videoReady} from './media.mjs';
import {originalPrompt,workflowSteps,tour,validPhases,executionSteps,toolHref} from './scenario.mjs';
const outputs=websiteCMSPreview(data);
const examples=[{id:'content',title:'Prepare five website pages',subtitle:'Full copy, SEO, CTA and asset requirements'},{id:'review',title:'Review changes and approvals',subtitle:'Compare source excerpts and exact draft versions'},{id:'handoff',title:'Prepare a developer handoff',subtitle:'Structured files and unpublished staging rules'},{id:'tools',title:'Explore the CMS screens',subtitle:'Four clearly labelled simulations'}];
function Feedback(){
 const questions=['Where would this help your website-content delivery process, if anywhere?','What would need to change or be validated before using it with a real client?','Would you consider evaluating a live version, and under what conditions?'];
 const [answers,setAnswers]=useState(['','','']);const [status,setStatus]=useState('');
 const copy=async()=>{try{await navigator.clipboard.writeText(questions.map((q,i)=>`${q}\n${answers[i]||'[Your response]'}`).join('\n\n'));setStatus('Feedback copied. Nothing has been submitted.');}catch{setStatus('Select and copy your answers directly. Nothing has been submitted.');}};
 return <section className="mx-auto max-w-2xl"><h1 className="text-2xl font-semibold">Your professional assessment</h1><p className="mt-3 text-sm leading-7 text-muted-foreground">Candid criticism is useful. This prepared demonstration does not establish live integrations, client approval or production readiness.</p><div className="mt-6 space-y-5">{questions.map((q,i)=><label key={q} className="block text-sm">{q}<textarea rows={3} value={answers[i]} onChange={e=>setAnswers(answers.map((a,j)=>i===j?e.target.value:a))} className="mt-2 w-full rounded-xl border border-white/10 bg-card/50 p-3 outline-none focus:border-primary/50"/></label>)}</div><p className="mt-5 text-xs leading-6 text-muted-foreground">If you provide feedback for an EB-2 NIW submission or confidential investor discussions, please state your role, what you reviewed and whether you permit each use. Public quotation requires separate permission.</p><button type="button" onClick={copy} className="mt-5 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm"><Copy className="h-4 w-4"/>Copy feedback</button><p role="status" className="mt-3 text-xs text-muted-foreground">{status||'Answers stay in this tab. No email or form submission is made.'}</p></section>;
}
export default function ShowcaseApp(){
 const location=useLocation();const navigate=useNavigate();const params=new URLSearchParams(location.search);
 const requestedScene=params.has('scene')?Number(params.get('scene')):-1;
 const [tourIndex,setTourIndex]=useState(Number.isInteger(requestedScene)&&tour[requestedScene]?requestedScene:params.get('tour')==='1'?0:-1);
 const [auto,setAuto]=useState(params.get('tour')==='1');
 const [seed,setSeed]=useState(originalPrompt);const [inputKey,setInputKey]=useState(0);const [error,setError]=useState('');const [progress,setProgress]=useState(0);const [history,setHistory]=useState(false);
 const previousLocation=useRef(location.search);
 const current=tourIndex>=0?tour[tourIndex]:null;
 const requestedPhase=params.get('screen')||'input';
 const phase=current?.phase||(validPhases.has(requestedPhase)?requestedPhase:'input');
 const focus=current?.focus||{tab:params.get('tab')||'Pages',page:params.get('page')||'p01',section:params.get('section')};
 const toolSlug=current?.tool||params.get('tool');const output=outputs.tools.find(t=>t.id===`${toolSlug}-preview`);
 const stop=()=>{setAuto(false);setTourIndex(-1);};
 const move=(screen)=>{stop();setError('');navigate(`?screen=${screen}`);};
 const start=()=>{navigate('?tour=1');setSeed(originalPrompt);setInputKey(k=>k+1);setTourIndex(0);setAuto(true);setError('');};
 const restore=()=>{setSeed(originalPrompt);setInputKey(k=>k+1);setError('');};
 useEffect(()=>{if(previousLocation.current!==location.search){previousLocation.current=location.search;if(!new URLSearchParams(location.search).has('tour')){setTourIndex(-1);setAuto(false);}}},[location.search]);
 useEffect(()=>{if(!current||!auto)return undefined;const t=window.setTimeout(()=>{if(tourIndex===tour.length-1)setAuto(false);else setTourIndex(i=>i+1);},current.seconds*1000);return()=>window.clearTimeout(t);},[auto,current,tourIndex]);
 useEffect(()=>{if(phase!=='execution')return undefined;setProgress(0);let n=0;const t=window.setInterval(()=>{n++;setProgress(n);if(n>=workflowSteps.length){window.clearInterval(t);if(!current)navigate('?screen=results');}},1200);return()=>window.clearInterval(t);},[phase,current,navigate]);
 useEffect(()=>{const t=window.setTimeout(()=>{if(phase==='results'&&focus.section==='tools')document.getElementById('website-tool-results')?.scrollIntoView({block:'start',behavior:'smooth'});else window.scrollTo({top:0,behavior:'instant'});},120);return()=>window.clearTimeout(t);},[phase,tourIndex,focus.section]);
 const controls=current&&<aside aria-label="Guided walkthrough" className="showcase-tour fixed bottom-4 left-1/2 z-50 w-[min(48rem,calc(100%-2rem))] -translate-x-1/2 rounded-2xl border border-primary/30 bg-[#111a2e]/95 p-4 text-white shadow-2xl"><div className="flex items-center justify-between"><p className="text-xs font-semibold text-violet-300">{tourIndex+1}/{tour.length} · {current.title}</p><button type="button" aria-label="Close walkthrough" onClick={()=>{const path=phase==='tool'?`tool&tool=${toolSlug}`:phase;move(path);}}><X className="h-4 w-4"/></button></div><p className="mt-2 text-xs leading-6 text-slate-300">{current.caption}</p><div className="mt-3 flex items-center justify-between"><button type="button" disabled={tourIndex===0} onClick={()=>{setAuto(false);setTourIndex(i=>Math.max(0,i-1));}} className="flex items-center gap-1 text-xs disabled:opacity-30"><ArrowLeft className="h-3 w-3"/>Back</button><button type="button" onClick={()=>setAuto(a=>!a)} className="flex items-center gap-1 text-xs text-violet-300">{auto?<Pause className="h-3 w-3"/>:<Play className="h-3 w-3"/>}{auto?'Pause':'Play'}</button><button type="button" disabled={tourIndex===tour.length-1} onClick={()=>{setAuto(false);setTourIndex(i=>Math.min(tour.length-1,i+1));}} className="flex items-center gap-1 text-xs disabled:opacity-30">Next<ArrowRight className="h-3 w-3"/></button></div></aside>;
 if(phase==='tool')return <>{output?<SimulatedCMSScreen key={`${output.id}-${current?.page||''}`} output={output} client={data.client} initialPageId={current?.page||null} backHref="?screen=results"/>:<main className="p-10"><h1>Unknown simulated tool</h1><Link to="?screen=results">Back to AURA results</Link></main>}{controls}</>;
 return <WorkspaceShell phase={phase==='execution'?'executing':phase} onHistoryOpen={()=>setHistory(!history)} footerText="AURA · Separate public demonstration">
 <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 px-5 py-3 text-[11px] text-muted-foreground"><span><strong className="text-violet-300">PREPARED DEMO</strong> · saved public-site example + simulated CMS screens · no sign-in</span><nav className="flex flex-wrap items-center gap-5" aria-label="Demo navigation"><button type="button" onClick={start} className="flex items-center gap-1.5 hover:text-white"><Play className="h-3 w-3"/>Watch walkthrough</button><button type="button" onClick={()=>move('results')} className="hover:text-white">Main result</button>{videoReady&&<button type="button" onClick={()=>move('video')} className="flex items-center gap-1.5 hover:text-white"><Video className="h-3 w-3"/>Watch video</button>}<button type="button" onClick={()=>move('feedback')} className="flex items-center gap-1.5 hover:text-white"><MessageSquare className="h-3 w-3"/>Feedback</button><button type="button" aria-label="Restart demo" onClick={()=>{restore();move('input');}}><RotateCcw className="h-3.5 w-3.5"/></button></nav></div>
 {history&&<div className="mx-auto mt-4 w-[min(50rem,95%)] rounded-xl border border-white/10 p-5 text-xs"><p>This public demo contains one prepared workflow and no account history.</p><button type="button" onClick={()=>{setHistory(false);move('results');}} className="mt-3 text-primary">Open five-page website content result</button></div>}
 <main className={`showcase-main mx-auto w-full flex-1 px-5 py-9 ${phase==='results'?'max-w-6xl':'max-w-5xl'} ${phase==='input'?'showcase-input':''}`}>
 <div className="w-full">{error&&<p role="alert" className="mb-5 text-sm text-amber-200">{error}<button type="button" onClick={restore} className="ml-2 underline">Restore prepared task</button></p>}
 {phase==='input'&&<CommandInput key={inputKey} initialValue={seed} examples={examples} onPickExample={restore} onSubmit={text=>{if(text.trim()!==originalPrompt.trim()){setError('This standalone demo follows the prepared website-content task. Restore it to continue.');return;}move('plan');}}/>}
 {phase==='plan'&&<ShowcasePlan onReview={()=>move('review')}/>}
 {phase==='review'&&<PreviewView steps={workflowSteps} readOnlySummary={<SourceReview/>} reviewDescription="Inspect the sources and proposed output. Approval starts only the local demonstration." approvalLabel="Start prepared demo" onApprove={()=>move('execution')} onBack={()=>move('plan')}/>}
 {phase==='execution'&&<><p role="note" className="mb-6 rounded-xl border border-violet-300/20 p-4 text-xs leading-6 text-violet-200">Prepared playback · saved website evidence and simulated CMS handoffs. No live provider calls, account connections, approvals or external writes.</p><ExecutionView steps={executionSteps(progress)} currentStepIndex={progress} demo/></>}
 {phase==='results'&&<WebsiteContentResult key={JSON.stringify(focus)} packet={data} demoMode initialTab={focus.tab||'Pages'} initialPage={focus.page} toolScreenHref={toolHref}/>}
 {phase==='feedback'&&<Feedback/>}
 {phase==='video'&&videoReady&&<section className="mx-auto max-w-4xl"><h1 className="text-2xl font-semibold">Website content workflow · video walkthrough</h1><p className="mt-3 text-sm leading-7 text-muted-foreground">A captioned walkthrough of the prepared AURA demo, followed by four simulated CMS screens. It uses interface views rendered from the isolated demo build; it does not show live provider execution. Audio is off.</p><video className="mt-6 w-full rounded-2xl border border-white/10 bg-black" controls playsInline preload="metadata" src="./walkthrough.mp4" poster="./walkthrough-poster.jpg"><track kind="captions" src="./walkthrough.vtt" srcLang="en" label="English"/>Your browser does not support this video.</video><div className="mt-5 flex gap-5 text-sm"><a href="./walkthrough.mp4" download className="text-primary underline">Download MP4</a><button type="button" onClick={start} className="text-primary">Try the interactive walkthrough</button></div></section>}
 {phase==='video'&&!videoReady&&<section><h1 className="text-2xl font-semibold">The video walkthrough is being prepared</h1><button type="button" onClick={start} className="mt-5 text-primary">Open the interactive walkthrough</button></section>}
 </div></main>{controls}</WorkspaceShell>;
}
