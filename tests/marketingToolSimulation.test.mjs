import test from 'node:test';
import assert from 'node:assert/strict';
import {executeMarketingSimulation,validateNativeMarketingPlan,runNativeMarketingChecks,nativeMarketingActivities} from '../src/lib/marketingToolSimulation.mjs';
import {parseMarketingDelivery} from '../src/lib/marketingToolResults.mjs';

const safe={steps:[{tool_slug:'google-ads',operation:'google-ads.list-account-id-options',arguments:{}},
  {tool_slug:'mailchimp',operation:'mailchimp.audiences.list',arguments:{count:10}}]};

test('separate adapters calculate their own performance and retain explicit browser provenance',async()=>{
  const meta=await executeMarketingSimulation('meta',{simulate:true,scenario:'maple_ember_v1'});
  const klaviyo=await executeMarketingSimulation('klaviyo',{simulate:true,scenario:'maple_ember_v1'});
  assert.equal(meta.comparison.previous.spend,1700);
  assert.equal(meta.comparison.current.spend,2100);
  assert.equal(meta.comparison.current.purchase_cpa,2100/55);
  assert.equal(klaviyo.comparison.current.clicks_rate,94/626);
  assert.equal(klaviyo.comparison.current.revenue,1920);
  assert.equal(klaviyo.rows.at(-1).delivered,0);
  assert.notEqual(meta.receipt.executor,klaviyo.receipt.executor);
  assert.equal(meta.receipt.fixture_sha256,klaviyo.receipt.fixture_sha256);
  assert.notEqual(meta.attribution,klaviyo.attribution);
  for(const output of [meta,klaviyo]) {
    assert.equal(output.receipt.mode,'browser_simulated_tool_adapter');
    assert.equal(output.receipt.provider_api_called,false);
    assert.equal(output.receipt.external_writes,false);
    assert.equal(output.receipt.native_drafts_saved,false);
    assert.match(output.receipt.fixture_sha256,/^[a-f0-9]{64}$/);
  }
  assert.equal(parseMarketingDelivery({kind:'marketing_tools',schemaVersion:1,packet:{simulations:[meta,klaviyo]}}).kind,'marketing_tools');
  assert.throws(()=>parseMarketingDelivery({kind:'marketing_tools',schemaVersion:1,packet:{simulations:[meta,{...klaviyo,synthetic:false}]}}));
  await assert.rejects(executeMarketingSimulation('google',{simulate:true,scenario:'maple_ember_v1'}));
  await assert.rejects(executeMarketingSimulation('meta',{simulate:false,scenario:'maple_ember_v1'}));
});

test('native plan guard rejects substitutions, hidden alternatives and excess data access',()=>{
  assert.equal(validateNativeMarketingPlan(safe),true);
  for(const edit of [
    {tool_slug:'aura'}, {operation:'mailchimp.campaign.send'}, {fallback_operation:'gmail.send'},
    {fallback_tool_slug:'aura'}, {arguments:{accountId:'unverified'}}, {condition:{left:true}},
  ]) assert.throws(()=>validateNativeMarketingPlan({steps:[{...safe.steps[0],...edit},safe.steps[1]]}));
  assert.throws(()=>validateNativeMarketingPlan({steps:[safe.steps[0],{...safe.steps[1],arguments:{count:100}}]}));
  assert.throws(()=>validateNativeMarketingPlan({steps:[...safe.steps,{tool_slug:'aura',operation:'report.compose'}]}));
});

test('coordinator approves only the validated native read plan and retains actual responses',async()=>{
  let approved=0,reads=0;
  const run={id:'run',status:'completed',steps:[{...safe.steps[0],status:'completed',output:{provider_result:{options:[]}}},
    {...safe.steps[1],status:'failed',error:'Provider unavailable'}]};
  const result=await runNativeMarketingChecks({createRun:async()=>({id:'run'}),getRun:async()=>++reads===1?{id:'run',status:'awaiting_approval',plan:safe}:run,
    approvePlan:async(id,edited,review)=>{assert.equal(id,'run');assert.equal(edited,null);assert.equal(review,true);approved++;}},()=>{},{pause:async()=>{},requestKey:'test'});
  assert.equal(approved,1);
  const activity=nativeMarketingActivities(result);
  assert.deepEqual(activity[0].output.provider_result,{options:[]});
  assert.equal(activity[1].status,'failed');
  assert.equal(activity[1].output,undefined);
});

test('failed or unsafe planning never calls an execution approval',async()=>{
  let approved=0;
  for(const run of [{id:'run',status:'failed',error:'Planning failed'},
    {id:'run',status:'awaiting_approval',plan:{steps:[{tool_slug:'aura',operation:'report.compose'}]}}]) {
    const result=await runNativeMarketingChecks({createRun:async()=>({id:'run'}),getRun:async()=>run,approvePlan:async()=>{approved++;}},()=>{},{pause:async()=>{},requestKey:'test'});
    assert.ok(nativeMarketingActivities(result).every(item=>item.status==='blocked' && !item.output));
  }
  assert.equal(approved,0);
});
