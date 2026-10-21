import test from 'node:test';
import assert from 'node:assert/strict';
import {marketingToolResult,marketingToolStates} from '../src/lib/marketingToolResults.mjs';
import {toolResultEntries,toolResultGroups} from '../src/lib/toolResultViews.mjs';

const simulation=(tool,operation)=>({operation,provider_result:{kind:'marketing_tool',tool,synthetic:true,
  receipt:{mode:'browser_simulated_tool_adapter',provider_api_called:false,external_writes:false}}});
const meta=simulation('Meta Ads','meta-ads-simulated.review.get');
const klaviyo=simulation('Klaviyo','klaviyo-simulated.lifecycle.get');
const native={operation:'google-ads.list-account-id-options',provider_result:{ret:[]}};

test('only explicit simulation receipts activate the per-tool marketing screen',()=>{
  assert.equal(marketingToolResult([{operation:'report.compose',provider_result:{body:'Meta Ads and Klaviyo'}}]),null);
  assert.equal(marketingToolResult([{...meta,provider_result:{...meta.provider_result,synthetic:false}}]),null);
  assert.equal(marketingToolResult([{...meta,provider_result:{...meta.provider_result,receipt:{...meta.provider_result.receipt,provider_api_called:true}}}]),null);
  assert.equal(marketingToolResult([meta]).kind,'marketing_tool');
  const result=marketingToolResult([native,meta,klaviyo]);
  assert.equal(result.kind,'marketing_tools');
  assert.deepEqual(result.packet.simulations.map(item=>item.tool),['Meta Ads','Klaviyo']);
});

test('native missing, failed and empty responses stay separate from simulated metrics',()=>{
  const states=marketingToolStates([
    {operation:native.operation,status:'completed',output:native},
    {operation:meta.operation,status:'completed',output:meta},
    {operation:'mailchimp.audiences.list',status:'failed',error:'Provider unavailable'},
    {operation:klaviyo.operation,status:'completed',output:klaviyo},
  ]);
  assert.deepEqual(states.map(tool=>tool.mode),['Native','Simulated','Native','Simulated']);
  assert.deepEqual(states[0].response,{ret:[]});
  assert.equal(states[2].label,'Needs attention');
  assert.equal(states[2].response,undefined);
  assert.equal(states[1].label,'Simulation completed');
  assert.equal(marketingToolStates([])[0].status,'not_run');
  assert.equal(marketingToolStates([{operation:native.operation,status:'completed',output:{provider_result:{error:'Read failed'}}}])[0].label,'Needs attention');
});

test('simulated adapters retain separate tool identities without an AURA execution step',()=>{
  const entries=toolResultEntries([
    {tool:'google-ads',status:'completed',output:native},
    {tool:'meta-ads-simulated',status:'completed',output:meta},
    {tool:'mailchimp',status:'completed',output:{operation:'mailchimp.audiences.list',provider_result:{lists:[]}}},
    {tool:'klaviyo-simulated',status:'completed',output:klaviyo},
  ]);
  assert.deepEqual(toolResultGroups(entries).map(group=>group.tool),['Google Ads','Meta Ads · Simulated','Mailchimp','Klaviyo · Simulated']);
  assert.equal(entries[1].synthetic,true);
  assert.equal(entries[0].synthetic,false);
});
