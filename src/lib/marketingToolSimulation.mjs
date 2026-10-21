import fixture from '../data/marketing_tools_maple_ember_v1.json' with { type: 'json' };

export const SIMULATION_OPERATIONS = Object.freeze({meta:'meta-ads-simulated.review.get',klaviyo:'klaviyo-simulated.lifecycle.get'});

export async function executeMarketingSimulation(tool,{simulate,scenario}={}) {
  if (!Object.hasOwn(SIMULATION_OPERATIONS,tool) || simulate!==true || scenario!=='maple_ember_v1') throw new Error('Authorize the exact Meta Ads or Klaviyo simulation scenario.');
  const source=structuredClone(fixture[tool]);
  const comparison={};
  for(const period of ['previous','current']) {
    const rows=source.rows.filter(row=>row.period===period);
    const metrics=tool==='meta'?['spend','purchases','revenue']:['delivered','clicks','orders','revenue','unsubscribes'];
    const totals=Object.fromEntries(metrics.map(metric=>[metric,rows.reduce((sum,row)=>sum+row[metric],0)]));
    if(tool==='meta') totals.purchase_cpa=totals.purchases?totals.spend/totals.purchases:null;
    else for(const key of ['clicks','unsubscribes']) totals[key+'_rate']=totals.delivered?totals[key]/totals.delivered:null;
    comparison[period]=totals;
  }
  const bytes=new TextEncoder().encode(JSON.stringify(fixture));
  const digest=await crypto.subtle.digest('SHA-256',bytes);
  const hash=[...new Uint8Array(digest)].map(value=>value.toString(16).padStart(2,'0')).join('');
  return {...source,kind:'marketing_tool',synthetic:true,scenario,
    brief:structuredClone(fixture.brief),periods:structuredClone(fixture.periods),
    timezone:'America/New_York',currency:'USD',comparison,
    receipt:{executor:source.tool+' simulation adapter',mode:'browser_simulated_tool_adapter',
      execution_location:'AURA browser',operation:SIMULATION_OPERATIONS[tool],
      executed_at:new Date().toISOString(),fixture_sha256:hash,provider_api_called:false,
      external_writes:false,native_drafts_saved:false}};
}

export const NATIVE_CHECK_PROMPT='Run exactly two native read-only discovery actions: Google Ads google-ads.list-account-id-options with empty arguments, and Mailchimp mailchimp.audiences.list with count 10. Use only those two connected tools. No report, AURA Intelligence step, analysis step, customer contacts, performance query, campaign creation, messages or other writes. This is account discovery only. Maple & Ember Coffee is fictional; do not select an unrelated account or claim a client mapping. Return each native response separately.';

export function validateNativeMarketingPlan(plan) {
  const steps=plan?.steps;
  if(!Array.isArray(steps) || steps.length!==2) throw new Error('Native checks require exactly the two approved discovery reads. No plan actions were approved.');
  const expected=new Map([['google-ads.list-account-id-options','google-ads'],['mailchimp.audiences.list','mailchimp']]);
  for(const step of steps) {
    if(expected.get(step.operation)!==step.tool_slug || step.fallback_operation || step.fallback_tool_slug || step.condition) throw new Error('The native plan contains an unapproved tool or alternative action. Nothing was approved.');
    const args=step.arguments || {};
    if(step.tool_slug==='google-ads' && Object.keys(args).length) throw new Error('Google account discovery must not select an account.');
    if(step.tool_slug==='mailchimp' && (Object.keys(args).some(key=>key!=='count') || (args.count!==undefined && (!Number.isInteger(args.count)||args.count<1||args.count>10)))) throw new Error('Mailchimp discovery is limited to ten audience metadata rows.');
    expected.delete(step.operation);
  }
  if(expected.size) throw new Error('An approved native discovery read is missing.');
  return true;
}

export async function runNativeMarketingChecks(api,onUpdate=()=>{},options={}) {
  const pause=options.pause || (ms=>new Promise(resolve=>setTimeout(resolve,ms)));
  let run;
  let approved=false;
  try {
    run=await api.createRun(NATIVE_CHECK_PROMPT,null,options.requestKey || crypto.randomUUID(),{requested_tools:['Google Ads','Mailchimp']});
    onUpdate(run);
    for(let poll=0;poll<(options.maxPolls || 45);poll++) {
      run=await api.getRun(run.id); onUpdate(run);
      if(['completed','failed','cancelled','waiting_for_connection','waiting_for_action','paused'].includes(run.status)) return {run};
      if(run.status==='awaiting_approval') {
        if(approved) return {run,error:'The native checks require additional review; no additional action was approved.'};
        validateNativeMarketingPlan(run.plan);
        await api.approvePlan(run.id,null,true); approved=true;
      }
      await pause(2000);
    }
    return {run,error:'Native checks are still pending. Their live workflow remains linked; no response has been invented.'};
  } catch(error) { return {run,error:error.message || 'Native discovery is unavailable.'}; }
}

export function nativeMarketingActivities(result) {
  return [['google-ads','google-ads.list-account-id-options'],['mailchimp','mailchimp.audiences.list']].map(([tool,operation])=>{
    const actual=(result.run?.steps || []).find(step=>step.operation===operation && step.tool_slug===tool);
    return actual?{...actual,stepKey:actual.key,tool,action:actual.reason || operation}
      : {id:'not-executed-'+tool,tool,operation,status:'blocked',action:'Native account discovery',
        error:result.error || result.run?.error || result.run?.blocker?.message || 'Native read was not executed. No provider response is saved.'};
  });
}
