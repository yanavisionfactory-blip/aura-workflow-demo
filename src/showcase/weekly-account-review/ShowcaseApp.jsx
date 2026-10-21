import { useEffect, useRef, useState } from 'react';
import { Check, Copy, Play, Pause, ArrowLeft, ArrowRight, RotateCcw, Video, Square, MessageSquare, X } from 'lucide-react';
import WorkspaceShell from '@/components/aura/WorkspaceShell';
import CommandInput from '@/components/aura/CommandInput';
import PreviewView from '@/components/aura/PreviewView';
import ExecutionView from '@/components/aura/ExecutionView';
import WeeklyReviewResult from '@/components/aura/WeeklyReviewResult';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import ShowcasePlan from './ShowcasePlan';
import SourceReview from './SourceReview';
import data from './data.mjs';
import { originalPrompt, workflowSteps, executionSteps, tour, validPhases } from './scenario.mjs';

const examples = [
  { id: 'review', title: 'Weekly account review', subtitle: 'Three scoped platforms and a reviewable plan' },
  { id: 'evidence', title: 'Check scope and metrics', subtitle: 'Aligned weeks and separate attribution' },
  { id: 'tests', title: 'Propose three tests', subtitle: 'Evidence, decision rules and implementation work' },
  { id: 'drafts', title: 'Review creative variants', subtitle: 'Search, social and email drafts in AURA' },
];

function Feedback() {
  const [values, setValues] = useState(['', '', '']);
  const [status, setStatus] = useState('');
  const questions = ['Where would this help your weekly account-review work, if anywhere?', 'What is missing or unclear before you would trust a live evaluation?', 'What would you change first, and what would you need to test?'];
  const copy = async () => {
    const text = questions.map((question, index) => `${question}\n${values[index] || '[Your response]'}`).join('\n\n');
    try { await navigator.clipboard.writeText(text); setStatus('Feedback copied. Nothing has been submitted.'); }
    catch { setStatus('Your browser blocked copying. Select and copy your answers directly.'); }
  };
  return <section className="mx-auto max-w-2xl"><h2 className="text-2xl font-semibold">Your professional feedback</h2><p className="mt-3 text-sm leading-6 text-muted-foreground">Candid criticism is useful. This prototype demonstrates a workflow using a fictional client and simulated platform metrics; it does not establish live tool performance.</p><div className="mt-6 space-y-5">{questions.map((question, index) => <label key={question} className="block text-sm">{question}<textarea rows={3} value={values[index]} onChange={(event) => setValues(values.map((value, i) => i === index ? event.target.value : value))} className="mt-2 w-full rounded-xl border border-white/10 bg-card/60 p-3 text-sm outline-none focus:border-primary/50"/></label>)}</div><p className="mt-4 text-xs leading-6 text-muted-foreground">If you choose to provide a professional assessment for an EB2 NIW filing or confidential investor discussions, please use your own words, state your role and what you actually reviewed, and give separate permission for those uses. Public quotation requires separate permission.</p><button type="button" onClick={copy} className="mt-5 flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm text-primary-foreground"><Copy className="h-4 w-4"/>Copy feedback</button><p role="status" className="mt-3 text-xs text-muted-foreground">{status || 'Answers stay in this tab. No email or form submission is made.'}</p></section>;
}

export default function ShowcaseApp({ initialPhase = 'input', initialTour = false, initialFocus = null }) {
  const [phase, setPhase] = useState(validPhases.has(initialPhase) ? initialPhase : 'input');
  const [inputSeed, setInputSeed] = useState(originalPrompt);
  const [inputKey, setInputKey] = useState(0);
  const [error, setError] = useState('');
  const [progress, setProgress] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [tourIndex, setTourIndex] = useState(initialTour ? 0 : -1);
  const [auto, setAuto] = useState(initialTour);
  const [recording, setRecording] = useState(false);
  const [recordingUrl, setRecordingUrl] = useState('');
  const [recordStatus, setRecordStatus] = useState('');
  const recorder = useRef(null);
  const recordingStream = useRef(null);
  const videoUrl = useRef('');
  const current = tourIndex >= 0 ? tour[tourIndex] : null;
  const focus = current?.focus || initialFocus;

  const stopRecording = () => {
    if (recorder.current?.state === 'recording') recorder.current.stop();
    recordingStream.current?.getTracks().forEach((track) => track.stop());
  };
  const stopTour = () => { setAuto(false); setTourIndex(-1); stopRecording(); };
  const startTour = () => {
    setInputSeed(originalPrompt); setInputKey((value) => value + 1);
    setPhase('input'); setTourIndex(0); setAuto(true); setError('');
  };
  const restart = () => {
    stopTour(); setPhase('input'); setError(''); setInputSeed(originalPrompt);
    setInputKey((value) => value + 1); setProgress(0);
  };
  const useExample = () => {
    setInputSeed(originalPrompt); setInputKey((value) => value + 1); setError('');
  };
  const move = (nextPhase) => { setPhase(nextPhase); setError(''); window.scrollTo({ top: 0, behavior: 'instant' }); };

  useEffect(() => {
    if (tourIndex < 0) return;
    if (tour[tourIndex].phase === 'execution') setProgress(0);
    setPhase(tour[tourIndex].phase);
  }, [tourIndex]);

  useEffect(() => {
    if (phase !== 'execution' || (tourIndex >= 0 && !auto)) return undefined;
    const timer = window.setInterval(() => setProgress((value) => value + 1), 2000);
    return () => window.clearInterval(timer);
  }, [phase, tourIndex, auto]);

  useEffect(() => {
    if (phase === 'execution' && progress >= workflowSteps.length) setPhase('results');
  }, [phase, progress]);

  useEffect(() => {
    if (!auto || !current) return undefined;
    const timer = window.setTimeout(() => {
      if (tourIndex === tour.length - 1) { setAuto(false); stopRecording(); }
      else setTourIndex((value) => value + 1);
    }, current.seconds * 1000);
    return () => window.clearTimeout(timer);
  }, [auto, tourIndex, current]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const anchor = focus?.tab === 'Tool activity' ? 'weekly-tool-rows' : focus?.tab === 'Creative drafts' ? 'weekly-creative-controls' : 'weekly-review-view';
      const panel = phase === 'results' && focus ? document.getElementById(anchor) : null;
      if (panel) panel.scrollIntoView({ block: 'start', behavior: 'smooth' });
      else window.scrollTo({ top: 0, behavior: 'instant' });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [phase, tourIndex, focus]);

  useEffect(() => () => {
    if (recorder.current?.state === 'recording') recorder.current.stop();
    recordingStream.current?.getTracks().forEach((track) => track.stop());
    if (videoUrl.current) URL.revokeObjectURL(videoUrl.current);
  }, []);

  const recordWalkthrough = async () => {
    if (!navigator.mediaDevices?.getDisplayMedia || typeof MediaRecorder === 'undefined') {
      setRecordStatus('Screen recording is unavailable in this browser. The guided walkthrough still plays here.'); return;
    }
    try {
      setRecordStatus('Select this browser tab in the screen-sharing picker to record the AURA interface.');
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: { displaySurface: 'browser', frameRate: 30 }, audio: false });
      recordingStream.current = stream;
      const mimeType = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', 'video/mp4'].find((type) => MediaRecorder.isTypeSupported(type));
      const capture = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks = []; recorder.current = capture;
      capture.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      capture.onstop = () => {
        const blob = new Blob(chunks, { type: capture.mimeType });
        if (videoUrl.current) URL.revokeObjectURL(videoUrl.current);
        videoUrl.current = URL.createObjectURL(blob); setRecordingUrl(videoUrl.current);
        setRecording(false); setAuto(false);
        setRecordStatus('Recording ready to download. It stays in this tab and is never uploaded.');
        stream.getTracks().forEach((track) => track.stop());
      };
      stream.getVideoTracks()[0].addEventListener('ended', stopRecording, { once: true });
      capture.start(1000); setRecording(true); setRecordStatus('Recording this tab. Captions and the real interface are included; audio is off.'); startTour();
    } catch (cause) {
      setRecordStatus(cause?.name === 'NotAllowedError' ? 'Recording was not started. You can continue the guided walkthrough.' : 'The browser could not start recording. You can continue the guided walkthrough.');
      recordingStream.current?.getTracks().forEach((track) => track.stop());
    }
  };

  return <WorkspaceShell phase={phase === 'execution' ? 'executing' : phase} onHistoryOpen={() => setHistoryOpen(true)} footerText="AURA · Weekly account review demo">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 px-4 py-2 text-[11px] text-muted-foreground sm:px-6"><span><strong className="font-medium text-violet-300">DEMO</strong> · SmartSites weekly-review example · Fictional client · 3 simulated sources · read-only</span><div className="flex flex-wrap items-center gap-4"><button type="button" onClick={startTour} className="flex items-center gap-1.5 hover:text-foreground"><Play className="h-3 w-3"/>Watch walkthrough</button><button type="button" onClick={recording ? stopRecording : recordWalkthrough} className={`flex items-center gap-1.5 hover:text-foreground ${recording ? 'text-red-300' : ''}`}>{recording ? <Square className="h-3 w-3"/> : <Video className="h-3 w-3"/>}{recording ? 'Stop recording' : 'Record walkthrough'}</button><button type="button" onClick={() => { stopTour(); move('feedback'); }} className="flex items-center gap-1.5 hover:text-foreground"><MessageSquare className="h-3 w-3"/>Feedback</button><button type="button" aria-label="Restart demo" onClick={restart}><RotateCcw className="h-3.5 w-3.5"/></button></div></div>
    {recordStatus && <div role="status" className="border-b border-white/5 px-4 py-2 text-center text-xs leading-6 text-muted-foreground">{recordStatus}{recordingUrl && <a href={recordingUrl} download={`aura-weekly-review-walkthrough.${recorder.current?.mimeType.includes('mp4') ? 'mp4' : 'webm'}`} className="ml-3 text-primary underline">Download recording</a>}</div>}
    <main className={`showcase-main mx-auto w-full flex-1 px-4 py-8 md:py-12 ${phase === 'results' ? 'max-w-3xl' : 'max-w-5xl'} ${phase === 'input' ? 'showcase-input' : ''}`}>
      <div className="w-full">
        {error && <div role="alert" className="mx-auto mb-5 max-w-3xl rounded-xl border border-amber-400/20 bg-amber-400/5 p-4 text-xs leading-6 text-amber-200">{error}<button type="button" onClick={useExample} className="ml-2 underline">Restore the original task</button></div>}
        {phase === 'input' && <CommandInput enableWeeklyReviewSetup={false} key={inputKey} initialValue={inputSeed} examples={examples} onPickExample={useExample} onSubmit={(text) => { if (text !== originalPrompt.trim()) { setError('This demo follows the prepared weekly-review workflow. Use an example card to load the unchanged task.'); setInputSeed(text); setInputKey((value) => value + 1); return; } stopTour(); move('plan'); }}/ >}
        {phase === 'plan' && <ShowcasePlan onReview={() => move('review')}/>}
        {phase === 'review' && <PreviewView steps={workflowSteps} readOnlySummary={<SourceReview/>} reviewDescription="Check the client scope, reporting periods, metric definitions and proposed outputs before local playback." approvalLabel="Approve & run demo" onApprove={() => { stopTour(); setProgress(0); move('execution'); }} onBack={() => move('plan')}/>}
        {phase === 'execution' && <><div role="note" className="mx-auto mb-5 max-w-4xl rounded-xl border border-violet-400/20 bg-violet-400/5 p-3 text-xs leading-6 text-violet-200">Prepared playback · all account metrics are simulated. Scope: Google Ads, Meta Ads and Klaviyo. No launches, budget changes or message sends.</div><ExecutionView steps={executionSteps(progress)} currentStepIndex={progress} demo/><div className="mt-6 flex justify-center"><button type="button" onClick={() => { stopTour(); move('plan'); }} className="text-xs text-muted-foreground hover:text-foreground">Stop playback and return to plan</button></div></>}
        {phase === 'results' && <><WeeklyReviewResult packet={data} focus={focus}/><div className="mt-8 flex justify-center gap-6 border-t border-white/10 pt-5 text-xs"><button type="button" onClick={restart} className="text-primary">New workflow</button><button type="button" onClick={() => { stopTour(); move('feedback'); }} className="text-muted-foreground">Share your feedback</button></div></>}
        {phase === 'feedback' && <Feedback/>}
      </div>
    </main>
    {current && <aside aria-label="Guided walkthrough" className="showcase-tour fixed bottom-4 left-1/2 z-40 w-[min(48rem,calc(100%-2rem))] -translate-x-1/2 rounded-2xl border border-primary/30 bg-[#111a2e]/95 p-4 shadow-2xl"><div className="flex items-center justify-between gap-3"><p className="text-xs font-semibold text-primary">{tourIndex + 1}/{tour.length} · {current.title}</p><button type="button" aria-label="Close walkthrough" onClick={stopTour}><X className="h-3.5 w-3.5 text-muted-foreground"/></button></div><p className="mt-2 text-xs leading-6 text-slate-300">{current.caption}</p><div className="mt-3 flex items-center justify-between"><button type="button" disabled={tourIndex === 0} onClick={() => { setAuto(false); setTourIndex((value) => Math.max(0, value - 1)); }} className="flex items-center gap-1 text-xs text-muted-foreground disabled:opacity-30"><ArrowLeft className="h-3 w-3"/>Back</button><button type="button" onClick={() => setAuto(!auto)} className="flex items-center gap-1 text-xs text-primary">{auto ? <Pause className="h-3 w-3"/> : <Play className="h-3 w-3"/>}{auto ? 'Pause' : 'Play'}</button><button type="button" disabled={tourIndex === tour.length - 1} onClick={() => { setAuto(false); setTourIndex((value) => Math.min(tour.length - 1, value + 1)); }} className="flex items-center gap-1 text-xs text-muted-foreground disabled:opacity-30">Next<ArrowRight className="h-3 w-3"/></button></div></aside>}
    <Dialog open={historyOpen} onOpenChange={setHistoryOpen}><DialogContent className="showcase-modal border-white/10"><DialogHeader><DialogTitle>My workflows</DialogTitle><DialogDescription>This public demo contains one prepared workflow. There is no account history or backend.</DialogDescription></DialogHeader><button type="button" onClick={() => { setHistoryOpen(false); stopTour(); move('results'); }} className="flex items-center gap-3 rounded-xl border border-white/10 p-4 text-left"><Check className="h-4 w-4 text-primary"/><span><span className="block text-sm font-medium">Weekly account review</span><span className="mt-1 block text-xs text-muted-foreground">Open the prepared result · 3 scoped sample sources</span></span></button></DialogContent></Dialog>
  </WorkspaceShell>;
}
