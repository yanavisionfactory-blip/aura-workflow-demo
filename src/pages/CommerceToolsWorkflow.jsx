import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, CheckCircle2, Loader2, ShieldCheck } from 'lucide-react';
import WorkspaceShell from '@/components/aura/WorkspaceShell';
import { connectAgentConnection, createPythonRun, getPythonRun, approvePythonPlan, decidePythonApproval, resumePythonRun } from '@/lib/auraApi';
import { aura } from '@/api/auraClient';
import { COMMERCE_ORDER, COMMERCE_TOOLS } from '@/lib/commerceToolContract.mjs';
import { runCommerceTools } from '@/lib/commerceToolWorkflow.mjs';

export default function CommerceToolsWorkflow() {
  const navigate = useNavigate();
  const [running, setRunning] = useState(false), [state, setState] = useState(null), [error, setError] = useState(''), [unsaved, setUnsaved] = useState(null);
  const save = async data => { const record = await aura.entities.Delivery.create(data); navigate('/results/' + record.id); };
  const run = async () => {
    if (running) return;
    setRunning(true); setError('');
    try {
      const data = await runCommerceTools({ connect: connectAgentConnection, createRun: createPythonRun, getRun: getPythonRun, approvePlan: approvePythonPlan, decideApproval: decidePythonApproval, resume: resumePythonRun }, setState);
      setUnsaved(data); await save(data);
    } catch (problem) { setError(problem.message); }
    finally { setRunning(false); }
  };
  return <WorkspaceShell onBack={() => navigate('/')} onHistoryOpen={() => navigate('/', { state: { openHistory: true } })}>
    <main className="mx-auto w-full max-w-5xl flex-1 px-5 py-12">
      <p className="text-xs uppercase tracking-[.2em] text-violet-300">Unstoprev · e-commerce marketing</p>
      <h1 className="mt-3 text-3xl font-semibold">One product. Four tools. A weekly action package.</h1>
      <p className="mt-4 max-w-3xl text-sm leading-7 text-muted-foreground">AURA executes separately connected Google Ads, Meta Ads Manager, Amazon Ads and Amazon Seller Central simulation tools. Each tool returns its own report and execution receipt. Seller Central runs first, before the advertising reviews.</p>
      <div className="mt-6 rounded-xl border border-violet-300/25 bg-violet-300/5 p-4 text-sm leading-7"><strong>Simulated data, real AURA orchestration.</strong> Harbor &amp; Field and ASIN B0SIMMUG16 are fictional. Reports compare October 12–18 with October 5–11, 2026, in USD / America/Chicago. These tools have no vendor credentials or publishing capabilities. The run saves review drafts only.</div>
      <ol className="my-7 grid gap-3 md:grid-cols-2">{COMMERCE_ORDER.map((key, i) => {
        const step = state?.run?.steps?.find(s => s.operation === COMMERCE_TOOLS[key].operation);
        return <li key={key} className="rounded-xl border border-white/10 bg-card/50 p-5"><div className="flex items-center justify-between gap-3"><h2 className="font-medium">{i + 1}. {COMMERCE_TOOLS[key].name}</h2>{step?.status === 'completed' ? <CheckCircle2 className="h-5 w-5 text-emerald-400"/> : running && (step?.status === 'executing' || state?.key === key) ? <Loader2 className="h-5 w-5 animate-spin text-primary"/> : <span className="text-[10px] text-violet-300">SIMULATED</span>}</div><p className="mt-2 text-xs leading-6 text-muted-foreground">{key === 'seller' ? 'Listing · traffic · units/session · total ASIN sales · inventory' : key === 'google' ? 'Search terms · ads · spend · purchase credits · CPA' : key === 'meta' ? 'Facebook & Instagram creatives · clicks · purchases · CPA' : 'Advertised product · search terms · attributed sales · ACoS'}</p><p className="mt-2 text-xs text-primary">{step?.status?.replaceAll('_',' ') || 'Ready to connect and review'}</p></li>;
      })}</ol>
      {state && <p role="status" className="mb-5 text-sm text-violet-200">{state.message}</p>}
      <button type="button" onClick={run} disabled={running} className="inline-flex items-center gap-3 rounded-xl bg-primary px-6 py-3 text-sm font-semibold disabled:opacity-50">{running ? <><Loader2 className="h-4 w-4 animate-spin"/>Running through AURA…</> : <>Run four-tool workflow<ArrowRight className="h-4 w-4"/></>}</button>
      <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="h-4 w-4"/>No AURA Intelligence tool step. No launches, budget changes, published copy or inventory changes.</p>
      {state?.run?.id && <Link to={'/runs/' + state.run.id} className="mt-5 inline-block text-xs text-primary underline">Open native workflow and execution receipts</Link>}
      {error && <div role="alert" className="mt-5 rounded-xl border border-amber-300/30 p-5 text-sm text-amber-200">{error}{unsaved && <button className="ml-4 underline" onClick={() => save(unsaved)}>Save completed outputs</button>}</div>}
    </main>
  </WorkspaceShell>;
}
