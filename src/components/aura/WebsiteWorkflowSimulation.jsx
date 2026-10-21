import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import WebsiteContentResult from './WebsiteContentResult';
import SimulatedCMSScreen from './SimulatedCMSScreen';
import { WEBSITE_SIMULATION_KEY, WEBSITE_SIMULATION_STEPS, prepareWebsiteSimulation, approveWebsiteSimulation, stageWebsiteSimulation, verifyWebsiteSimulation } from '@/lib/websiteSimulation.mjs';

const savedKey = id => `${WEBSITE_SIMULATION_KEY}.${id}`;
export default function WebsiteWorkflowSimulation({ onBack, baseQuery = 'website=1&simulation=browser' }) {
  const location = useLocation(), navigate = useNavigate();
  const [packet, setPacket] = useState(null), [steps, setSteps] = useState({});
  const [running, setRunning] = useState(false), [restoring, setRestoring] = useState(true);
  const [approved, setApproved] = useState(false), [error, setError] = useState(''), [saved, setSaved] = useState(false);
  const locked = useRef(false);
  const run = packet?.simulationExecution, complete = run?.status === 'completed';
  const tool = new URLSearchParams(location.search).get('tool');
  const path = (id, slug) => `?${baseQuery}&run=${encodeURIComponent(id)}${slug ? `&tool=${slug}` : ''}`;
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const requested = new URLSearchParams(window.location.search).get('run');
        const id = requested || localStorage.getItem(WEBSITE_SIMULATION_KEY);
        if (!id) return;
        if (!/^[a-f0-9-]{36}$/.test(id)) throw new Error('Invalid saved simulation link.');
        const text = localStorage.getItem(savedKey(id));
        if (!text || text.length > 2000000) throw new Error('This simulation is not saved in this browser. Start a new run below.');
        const result = await verifyWebsiteSimulation(JSON.parse(text));
        if (!cancelled) { setPacket(result); setSaved(true); }
      } catch (cause) { if (!cancelled) setError(cause.message); }
      finally { if (!cancelled) setRestoring(false); }
    })();
    return () => { cancelled = true; };
  }, []);
  const onStep = async step => {
    setSteps(previous => ({ ...previous, [step.key]: step.status }));
    // Let the browser paint actual progress; no staged playback timer.
    await new Promise(resolve => window.requestAnimationFrame(resolve));
  };
  const keep = result => {
    setPacket(result); setSaved(false);
    try {
      localStorage.setItem(savedKey(result.simulationExecution.id), JSON.stringify(result));
      localStorage.setItem(WEBSITE_SIMULATION_KEY, result.simulationExecution.id); setSaved(true);
    } catch { setError('The workflow completed, but browser storage is full. Download the website files before leaving.'); }
    navigate(path(result.simulationExecution.id), { replace: true });
  };
  const prepare = async () => {
    if (locked.current) return;
    locked.current = true; setRunning(true); setError(''); setPacket(null); setSaved(false); setApproved(false); setSteps({});
    try { keep(await prepareWebsiteSimulation({ onStep })); }
    catch (cause) { setError(cause.message); }
    finally { locked.current = false; setRunning(false); }
  };
  const stage = async () => {
    if (locked.current || !approved) return;
    locked.current = true; setRunning(true); setError('');
    try { keep(await stageWebsiteSimulation(await approveWebsiteSimulation(packet), { onStep })); }
    catch (cause) { setError(cause.message); }
    finally { locked.current = false; setRunning(false); }
  };
  const output = complete && run.tools.find(item => item.id === `${tool}-preview`);
  if (output) return <SimulatedCMSScreen output={output} client={packet.client} backHref={path(run.id)}/>;
  const execution = <ol aria-label="Website simulation execution steps" className="grid gap-2 text-xs sm:grid-cols-2">{WEBSITE_SIMULATION_STEPS.map((step, index) => <li key={step.key} className="rounded-lg border border-white/10 p-3"><span className="font-medium">{index + 1}. {step.name}</span><span className="ml-2 text-emerald-200">{complete || run?.receipts.some(receipt => receipt.key === step.key) ? 'Completed' : steps[step.key] || (step.key === 'approval' && packet ? 'Your review needed' : 'Ready')}</span></li>)}</ol>;
  return <div aria-label="Runnable website workflow simulation" className="mx-auto w-full max-w-6xl space-y-6">
    <header className="rounded-2xl border border-primary/30 bg-card/50 p-5">
      <button type="button" disabled={running} onClick={onBack} className="mb-4 text-xs text-muted-foreground">Back to AURA</button>
      <p className="text-xs font-semibold text-primary">AURA · Executed simulation · Four CMS tools</p>
      <h1 className="mt-2 text-2xl font-semibold">{complete ? 'Website workflow completed · 12 of 12 steps' : packet ? 'Review your sample content package' : 'Run the five-page website workflow'}</h1>
      <p className="mt-2 text-sm text-slate-300">Kastner Hill Learning · labelled sample inputs</p>
      <p className="mt-3 text-sm leading-7 text-muted-foreground">AURA processes sample website pages, a sitemap, a brand brief and an image manifest. After your demo approval, four local CMS adapters create and read back unpublished sample drafts. Copy is authored sample content. No live vendor connection, AI generation, client approval or website change is claimed.</p>
      {complete && <p role="status" className="mt-4 text-sm font-semibold text-emerald-200">20 simulated drafts created · 20 readbacks passed · 0 live pages changed</p>}
      {saved && <p className="mt-3 text-xs text-muted-foreground">Saved in this browser. Download the website files for a portable record.</p>}
      {error && <p role="alert" className="mt-4 text-sm text-amber-200">{error}</p>}
      {!packet && <><div className="my-5">{execution}</div><button type="button" disabled={running || restoring} onClick={prepare} className="rounded-xl bg-primary px-5 py-3 text-sm font-semibold disabled:opacity-50">{restoring ? 'Checking saved run…' : running ? 'Processing sample inputs…' : 'Start website workflow with simulated data'}</button></>}
    </header>
    {packet && <WebsiteContentResult packet={packet} demoMode toolOutputs={complete ? run.tools : []} demoApproval={complete} toolScreenHref={id => path(run.id, id.replace('-preview', ''))}/>}
    {packet && !complete && <section aria-label="Demo approval" className="space-y-4 rounded-2xl border border-primary/30 p-5"><h2 className="text-xl font-semibold">Approve the sample package before draft staging</h2><p className="text-sm leading-7 text-muted-foreground">Review Pages, Changes, Approvals and Developer handoff above. This decision applies only to these sample versions and the sample image manifest. Actual client copy approval and image rights stay pending.</p><label className="flex items-start gap-3 text-sm leading-6"><input type="checkbox" checked={approved} disabled={running} onChange={event => setApproved(event.target.checked)} className="mt-1"/>I approve the sample copy and image manifest for this simulation only.</label><button type="button" onClick={stage} disabled={!approved || running} className="rounded-xl bg-primary px-5 py-3 text-sm font-semibold disabled:opacity-50">{running ? 'Creating and checking simulated drafts…' : 'Create and verify drafts in all four simulated CMS tools'}</button><div>{execution}</div></section>}
    {complete && <section className="space-y-4 rounded-2xl border border-white/10 p-5"><h2 className="text-lg font-semibold">Everything checked before completion</h2><p className="text-sm leading-7 text-muted-foreground">Each CMS has five separate unpublished records. Readback checks cover page copy, headings, buttons, search fields and image requirements. All protected sample live pages are unchanged. WooCommerce content is stored as WordPress pages; products, orders and checkout are untouched.</p><details><summary className="cursor-pointer text-sm text-primary">See all 12 completed workflow steps</summary><div className="mt-4">{execution}</div></details><button type="button" onClick={prepare} disabled={running} className="rounded-lg border border-primary/30 px-4 py-3 text-sm text-primary">Run a new website simulation</button></section>}
  </div>;
}
