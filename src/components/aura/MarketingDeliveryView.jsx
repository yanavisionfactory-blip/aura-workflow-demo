import { useEffect, useState } from 'react';
import MarketingResultsSummary from './MarketingResultsSummary';
import { getPythonRun } from '@/lib/auraApi';
import { nativeMarketingActivities } from '@/lib/marketingToolSimulation.mjs';
import { redactEvidence } from '@/lib/toolEvidence.mjs';

export default function MarketingDeliveryView({data}) {
  const simulations=(data.activity || []).filter(step=>step.output?.provider_result?.synthetic===true
    && step.output?.provider_result?.receipt?.mode==='browser_simulated_tool_adapter');
  const [native,setNative]=useState(()=>nativeMarketingActivities({error:data.nativeCheckError || 'No current native response has been verified.'}));
  const [error,setError]=useState('');
  useEffect(()=>{
    let active=true;
    if(data.sourceRunId) getPythonRun(data.sourceRunId).then(run=>{if(active)setNative(redactEvidence(nativeMarketingActivities({run,error:data.nativeCheckError})));})
      .catch(()=>{if(active)setError('Native source responses could not be refreshed. No native success is claimed.');});
    return ()=>{active=false;};
  },[data.sourceRunId,data.nativeCheckError]);
  const download=()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify({...data,activity:[...native,...simulations]},null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='AURA_Marketing_Tool_Outputs.json';link.click();URL.revokeObjectURL(url);
  };
  return <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8 md:py-12"><MarketingResultsSummary packet={data.packet} activity={[...native,...simulations]} onDownload={download} sourceRunId={data.sourceRunId}/>
    {error && <p role="status" className="mb-5 text-sm text-amber-200">{error}</p>}
  </main>;
}
