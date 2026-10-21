import { useEffect, useState } from 'react';
import ApprovedWeeklyReviewResult from './ApprovedWeeklyReviewResult';
import { WEEKLY_PLATFORMS } from '@/lib/weeklyReviewIntake.mjs';
import { BROWSER_WEEKLY_KEY, runBrowserWeeklySimulation, verifySavedBrowserSimulation } from '@/lib/browserWeeklySimulation.mjs';

export default function BrowserWeeklySimulation({ onBack }) {
  const [packet, setPacket] = useState(null), [steps, setSteps] = useState({});
  const [running, setRunning] = useState(false), [error, setError] = useState(''), [saved, setSaved] = useState(false);
  const [restoring, setRestoring] = useState(true);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const value = localStorage.getItem(BROWSER_WEEKLY_KEY);
        if (value && value.length < 400000) {
          const checked = await verifySavedBrowserSimulation(JSON.parse(value));
          if (!cancelled) { setPacket(checked); setSaved(true); }
        }
      } catch { if (!cancelled) setError('The previous local simulation could not be verified. Start a new run.'); }
      finally { if (!cancelled) setRestoring(false); }
    })();
    return () => { cancelled = true; };
  }, []);
  const run = async () => {
    setRunning(true); setError(''); setPacket(null); setSaved(false); setSteps({});
    try {
      const result = await runBrowserWeeklySimulation({ onStep: step => setSteps(previous => ({ ...previous, [step.key]: step.status })) });
      setPacket(result);
      try { localStorage.setItem(BROWSER_WEEKLY_KEY, JSON.stringify(result)); setSaved(true); }
      catch { setError('Run completed. Browser storage is unavailable; download the review and evidence before leaving.'); }
    } catch (cause) { setError(cause.message); }
    finally { setRunning(false); }
  };
  return <div className="mx-auto max-w-5xl space-y-5" aria-label="AURA browser simulation">
    <button type="button" disabled={running} onClick={onBack} className="text-xs text-muted-foreground">Back to review setup</button>
    <section className="space-y-4 rounded-2xl border border-primary/30 bg-card/50 p-5">
      <p className="text-xs font-semibold text-primary">AURA · Browser simulation · Seven platform adapters</p>
      <h1 className="text-2xl font-semibold">{packet ? 'Simulation completed · 8 of 8 steps' : 'Run the seven-platform account review'}</h1>
      <p className="text-sm leading-6 text-muted-foreground">This route executes sample parsing, arithmetic, SHA-256 hashing and proposal checks in your browser. It uses authored scenario drafts. No backend model, vendor API, campaign, budget or message action runs. Account scope, goals and brand brief are fictional assumptions; email cohorts only, no SMS.</p>
      <ol aria-label="Simulation execution steps" className="grid gap-2 text-xs sm:grid-cols-2">{[...WEEKLY_PLATFORMS, { key: 'review', name: 'Summary, experiments, drafts and backlog checks' }].map(item => <li key={item.key} className="rounded-lg border border-white/10 p-3">{item.name} · {packet ? 'completed' : steps[item.key] || 'ready'}{item.key !== 'review' && ' · simulated input'}</li>)}</ol>
      <button type="button" disabled={running || restoring} onClick={run} className="rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-white disabled:opacity-50">{restoring ? 'Checking saved simulation…' : running ? 'Processing simulation…' : packet ? 'Run a new browser simulation' : 'Run all eight simulation steps'}</button>
      {packet && <p className="break-all text-xs leading-6 text-muted-foreground">Run {packet.execution.id} · {packet.execution.executed_at} · {saved ? 'Saved in this browser; download for a portable record. This is not a backend workflow-history entry.' : 'Download to retain this result.'}</p>}
      {error && <p role="alert" className="text-sm text-amber-200">{error}</p>}
    </section>
    {packet && <ApprovedWeeklyReviewResult packet={packet}/>}
  </div>;
}
