import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FlaskConical, Loader2 } from 'lucide-react';
import WorkspaceShell from '@/components/aura/WorkspaceShell';
import MarketingToolResults from '@/components/aura/MarketingToolResults';
import { aura } from '@/api/auraClient';
import { createPythonRun, getPythonRun, approvePythonPlan } from '@/lib/auraApi';
import { redactEvidence } from '@/lib/toolEvidence.mjs';
import { executeMarketingSimulation, nativeMarketingActivities, runNativeMarketingChecks, SIMULATION_OPERATIONS } from '@/lib/marketingToolSimulation.mjs';

export default function MarketingToolsWorkflow() {
  const navigate=useNavigate();
  const [running,setRunning]=useState(false);
  const [nativeStatus,setNativeStatus]=useState('Not started');
  const [packet,setPacket]=useState(null);
  const [activity,setActivity]=useState([]);
  const [error,setError]=useState('');
  const [unsaved,setUnsaved]=useState(null);
  const save=async data=>{
    const stored=await aura.entities.Delivery.create(data);
    navigate(`/results/${stored.id}`,{replace:true});
  };
  const run=async()=>{
    if(running) return;
    setRunning(true); setError(''); setUnsaved(null);
    try {
      const simulations=[]; const simulatedActivity=[];
      for(const key of ['meta','klaviyo']) {
        const started=new Date().toISOString();
        const output=await executeMarketingSimulation(key,{simulate:true,scenario:'maple_ember_v1'});
        simulations.push(output);
        simulatedActivity.push({id:crypto.randomUUID(),tool:key==='meta'?'meta-ads-simulated':'klaviyo-simulated',
          operation:SIMULATION_OPERATIONS[key],action:`Run the ${output.tool} simulation`,status:'completed',
          started_at:started,completed_at:output.receipt.executed_at,
          output:{operation:SIMULATION_OPERATIONS[key],provider_result:output,
            resolved_arguments:{simulate:true,scenario:'maple_ember_v1'}}});
      }
      setPacket({simulations}); setActivity(simulatedActivity);
      const result=await runNativeMarketingChecks({createRun:createPythonRun,getRun:getPythonRun,approvePlan:approvePythonPlan},
        state=>setNativeStatus(state.status.replaceAll('_',' ')));
      const combined=redactEvidence([...nativeMarketingActivities(result),...simulatedActivity]);
      setActivity(combined);
      const data={kind:'marketing_tools',schemaVersion:1,title:'Maple & Ember — marketing tool outputs',
        client:'Maple & Ember Coffee',agency:'Agency demo',preparedAt:new Date().toISOString(),
        summary:'Native Google Ads and Mailchimp discovery checks with separately executed Meta Ads and Klaviyo browser simulations.',
        sourceRunId:result.run?.id || null,nativeCheckError:result.error || null,
        packet:{simulations},activity:combined};
      setUnsaved(data);
      await save(data);
    } catch(problem) { setError(problem.message || 'The outputs could not be saved.'); }
    finally { setRunning(false); }
  };
  return <WorkspaceShell onBack={()=>navigate('/')} onHistoryOpen={()=>navigate('/results')}>
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 md:py-12">
      {!packet && <section className="mx-auto max-w-3xl rounded-2xl border border-white/10 bg-card/50 p-6 sm:p-9"><FlaskConical className="h-8 w-8 text-violet-300"/><h1 className="mt-5 text-2xl font-semibold">Run the marketing tool workflow</h1><p className="mt-4 text-sm leading-7 text-muted-foreground">Google Ads and Mailchimp run native account and audience discovery. Meta Ads and Klaviyo run separate, explicitly simulated adapters using the fictional Maple & Ember Coffee scenario.</p><p className="mt-3 text-sm leading-7 text-muted-foreground">Each tool has its own output. AURA coordinates the work and saves the results for review. Same-client selection remains required before live performance queries. All campaign and email assets are proposals.</p><button type="button" onClick={run} disabled={running} className="mt-6 rounded-xl bg-primary px-5 py-3 text-sm font-semibold disabled:opacity-50">Run workflow</button></section>}
      {running && <p role="status" className="mb-5 flex items-center gap-3 rounded-xl border border-primary/25 p-4 text-sm"><Loader2 className="h-4 w-4 animate-spin"/>Meta Ads and Klaviyo simulations completed · native checks: {nativeStatus}</p>}
      {packet && <MarketingToolResults packet={packet} activity={activity}/>}
      {error && <div role="alert" className="mt-5 rounded-xl border border-amber-300/20 p-4 text-sm text-amber-200"><p>{error}</p>{unsaved && <button type="button" disabled={running} className="mt-3 rounded-lg bg-primary px-4 py-2 text-white" onClick={async()=>{setRunning(true);try{await save(unsaved);}catch(problem){setError(problem.message);}finally{setRunning(false);}}}>Save completed outputs</button>}</div>}
    </main>
  </WorkspaceShell>;
}
