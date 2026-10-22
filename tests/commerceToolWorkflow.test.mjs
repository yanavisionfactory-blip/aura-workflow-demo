import test from 'node:test';
import assert from 'node:assert/strict';
import { createCommerceServer } from '../server/commerce-tools.mjs';
import { COMMERCE_ARGS, COMMERCE_ORDER, COMMERCE_TOOLS, commerceToolResponse, commerceRunSteps, validateCommercePlan, buildCommerceDelivery } from '../src/lib/commerceToolContract.mjs';
import { runCommerceTools } from '../src/lib/commerceToolWorkflow.mjs';

test('four independent remote MCP tools calculate source-specific results and reject other actions', async t => {
  const server=createCommerceServer(); await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const base='http://127.0.0.1:'+server.address().port;
  const receipts=[];
  for(const key of COMMERCE_ORDER) {
    const call=async(method,params)=>{const r=await fetch(base+'/'+key+'/mcp',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});return r.json();};
    assert.ok((await call('initialize',{protocolVersion:'2025-03-26'})).result.serverInfo.name.includes('Simulated'));
    const tools=(await call('tools/list',{})).result.tools;
    assert.equal(tools.length,1); assert.equal(tools[0].name,COMMERCE_TOOLS[key].operation); assert.equal(tools[0].annotations.readOnlyHint,true);
    const result=(await call('tools/call',{name:tools[0].name,arguments:COMMERCE_ARGS})).result;
    const source=result.structuredContent; receipts.push(source.receipt.id);
    assert.equal(source.tool_key,key); assert.equal(source.receipt.execution_location,'Render'); assert.equal(source.receipt.external_writes,false); assert.equal(source.receipt.provider_api_called,false);
    if(key==='seller') assert.ok(Math.abs(source.readiness.daysCover-.7)<1e-10);
    if(key==='google') { assert.equal(source.comparison.current.spend,3298); assert.equal(source.comparison.current.purchases,110); assert.deepEqual(source.copy.headlines.map(x=>x.length),[24,21]); assert.ok(source.copy.description.length<=90); }
    if(key==='meta') { assert.equal(source.comparison.current.spend,2500); assert.equal(source.comparison.current.purchases,74); }
    if(key==='amazon') { assert.equal(source.comparison.current.sales,6720); assert.equal(source.comparison.current.spend,1750); }
    assert.equal((await call('tools/call',{name:'publish',arguments:COMMERCE_ARGS})).result.isError,true);
    assert.equal((await call('tools/call',{name:tools[0].name,arguments:{...COMMERCE_ARGS,simulate:false}})).result.isError,true);
    assert.equal((await call('tools/call',{name:tools[0].name,arguments:{...COMMERCE_ARGS,budget:999}})).result.isError,true);
  }
  assert.equal(new Set(receipts).size,4);
});

const connections=Object.fromEntries(COMMERCE_ORDER.map(key=>[key,{slug:'sim-'+key,name:COMMERCE_TOOLS[key].name+' · Simulated'}]));
async function completedRun() {
  const steps=commerceRunSteps(connections);
  for(const [i,step] of steps.entries()) { step.id='step-'+i; step.status='completed'; step.started_at=i===0?'2026-10-22T12:00:00Z':'2026-10-22T12:00:02Z'; step.completed_at=i===0?'2026-10-22T12:00:01Z':'2026-10-22T12:00:03Z'; step.output={provider_result:{is_error:false,schema_validation:{status:'passed'},structured_content:await commerceToolResponse(step.key,COMMERCE_ARGS,'https://sim.example')}}; }
  return {id:'native-run',status:'completed',steps};
}
test('native package rejects missing receipts, wrong ordering, unfinished or extra Intelligence steps',async()=>{
  const run=await completedRun(); assert.equal(buildCommerceDelivery(run,connections).activity.length,4);
  for(const mutate of [r=>r.steps.pop(),r=>r.status='waiting_for_action',r=>r.steps.push({operation:'report.compose'}),r=>r.steps[1].started_at='2026-10-22T11:00:00Z',r=>delete r.steps[1].output.provider_result.structured_content]) { const invalid=structuredClone(run); mutate(invalid); assert.throws(()=>buildCommerceDelivery(invalid,connections)); }
});
test('planner cannot substitute another tool or add report.compose',()=>{
  const plan={steps:commerceRunSteps(connections)}; assert.doesNotThrow(()=>validateCommercePlan(plan,connections));
  assert.throws(()=>validateCommercePlan({steps:[...plan.steps,{operation:'report.compose',tool_slug:'aura'}]},connections));
  assert.throws(()=>validateCommercePlan({steps:plan.steps.map((s,i)=>i===0?{...s,fallback_operation:'report.compose'}:s)},connections));
});
test('workflow executes native connection/planning/approval flow and waits for complete receipts',async()=>{
  const done=await completedRun(); let poll=0, approvedSteps;
  const result=await runCommerceTools({connect:async p=>Object.values(connections).find(x=>x.name===p.name),createRun:async()=>({id:'native-run'}),getRun:async()=>poll++===0?{id:'native-run',status:'awaiting_approval',plan:{steps:commerceRunSteps(connections)},steps:[]}:done,approvePlan:async(_id,steps)=>{approvedSteps=steps},decideApproval:async()=>{throw Error('not expected')}},()=>{}, {pause:async()=>{},maxPolls:3});
  assert.equal(result.kind,'commerce_tools'); assert.deepEqual(approvedSteps.map(s=>s.key),COMMERCE_ORDER); assert.ok(approvedSteps.slice(1).every(s=>s.depends_on.includes('seller')));
});
