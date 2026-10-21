import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { unzipSync, strFromU8 } from 'fflate';
import sample from '../src/showcase/website-content/data.mjs';
import { websiteContentZip } from '../src/lib/websiteContentExport.mjs';
import { websiteSimulationInputs, prepareWebsiteSimulation, approveWebsiteSimulation, stageWebsiteSimulation, verifyWebsiteSimulation, createSimulatedWebsiteAdapter } from '../src/lib/websiteSimulation.mjs';

const execute = async options => stageWebsiteSimulation(await approveWebsiteSimulation(await prepareWebsiteSimulation()), options);
test('website simulation executes 12 steps and 40 CMS operations with 20 checked unpublished records', async () => {
  const steps = [], network = globalThis.fetch;
  globalThis.fetch = () => { throw new Error('No network is allowed in this simulation.'); };
  try {
    const before = JSON.stringify(sample);
    const prepared = await prepareWebsiteSimulation({ onStep: step => steps.push(step) });
    assert.equal(prepared.simulationExecution.status, 'awaiting_demo_approval');
    assert.equal(prepared.simulationExecution.tools.length, 0);
    const packet = await stageWebsiteSimulation(await approveWebsiteSimulation(prepared), { onStep: step => steps.push(step) });
    const run = packet.simulationExecution;
    assert.equal(run.status, 'completed');
    assert.equal(steps.filter(step => step.status === 'completed').length, 12);
    assert.equal(run.simulated_records_created, 20);
    assert.equal(run.verified_readbacks, 20);
    assert.equal(run.model_call_executed, false);
    assert.equal(run.provider_api_called, false);
    assert.equal(run.external_writes, false);
    assert.equal(run.live_pages_modified, false);
    assert.equal(new Set(run.tools.flatMap(tool => tool.pages.map(page => page.simulated_record_id))).size, 20);
    for (const tool of run.tools) {
      assert.equal(tool.operations.length, 10);
      assert.deepEqual(tool.protected_live_before, tool.protected_live_after);
      for (const page of tool.pages) {
        assert.equal(page.readback_verified, true);
        assert.equal(page.approval_status, 'approved_for_simulation_only');
        assert.equal(page.content_blocks.length, 4);
        assert.ok(page.body_html.includes(page.cta.target));
        assert.ok(page.seo.meta_description.length > 30);
      }
    }
    const byName = name => run.tools.find(tool => tool.name === name).pages[0].provider_record;
    assert.equal(byName('WordPress').status, 'draft');
    assert.equal(byName('Shopify').published, false);
    assert.equal(byName('Shopify').published_at, null);
    assert.equal(byName('WooCommerce').content_owner, 'WordPress');
    assert.equal(byName('BigCommerce').is_visible, false);
    assert.ok(packet.pages.every(page => page.approval.status === 'pending' && page.approval.reviewer === null));
    assert.deepEqual(packet.systems, sample.systems);
    assert.equal(JSON.stringify(sample), before);
    assert.equal(prepared.simulationExecution.tools.length, 0);
    assert.deepEqual(await verifyWebsiteSimulation(JSON.parse(JSON.stringify(packet))), packet);
    const files = unzipSync(websiteContentZip(packet));
    assert.equal(Object.keys(files).filter(name => name.startsWith('pages/')).length, 5);
    assert.match(strFromU8(files['SIMULATION.txt']), /Shopify: 5 simulated unpublished records; 5 verified readbacks/);
    assert.equal(JSON.parse(strFromU8(files['simulation-evidence.json'])).tools.length, 4);
    assert.equal(JSON.parse(strFromU8(files['metadata.json'])).cms_drafts_created, 0);
    assert.equal(JSON.parse(strFromU8(files['metadata.json'])).simulation.simulated_records_created, 20);
  } finally { globalThis.fetch = network; }
});

test('source processing rejects missing and relabelled inputs; staging requires exact demo approval', async () => {
  const inputs = websiteSimulationInputs(); inputs.assets.pop();
  await assert.rejects(prepareWebsiteSimulation({ inputs }), /complete labelled sample/);
  const relabelled = websiteSimulationInputs(); relabelled.mode = 'approved_client_export';
  await assert.rejects(prepareWebsiteSimulation({ inputs: relabelled }), /complete labelled sample/);
  const packet = await prepareWebsiteSimulation();
  await assert.rejects(stageWebsiteSimulation(packet), /Approve the sample/);
  const approved = await approveWebsiteSimulation(packet);
  approved.pages[0].sections[0].body = 'Changed after approval';
  await assert.rejects(stageWebsiteSimulation(approved), /reviewed copy/);
  const assetChange = await approveWebsiteSimulation(packet);
  assetChange.simulationExecution.inputs.assets[0].approvedForSimulation = false;
  await assert.rejects(stageWebsiteSimulation(assetChange), /complete labelled sample/);
});

test('a provider readback failure or live-fixture mutation prevents workflow completion', async () => {
  for (const failure of ['publish', 'body', 'live']) {
    const factory = (provider, runId, pages) => {
      const adapter = createSimulatedWebsiteAdapter(provider, runId, pages);
      if (provider !== 'wordpress') return adapter;
      if (failure === 'live') {
        let reads = 0;
        return { ...adapter, liveSnapshot: () => { const live = adapter.liveSnapshot(); if (++reads > 1) live[0].status = 'draft'; return live; } };
      }
      return { ...adapter, readDraft: id => { const record = adapter.readDraft(id); if (failure === 'publish') record.status = 'publish'; else record.content.rendered = 'Incorrect body'; return record; } };
    };
    await assert.rejects(execute({ adapterFactory: factory }), /readback did not match|live-page fixture changed/);
  }
});

test('saved simulation verifies bodies, SEO, status, normalized views, operation receipts and input hashes', async () => {
  const original = await execute();
  const mutations = [
    packet => { packet.simulationExecution.tools[0].pages[0].provider_record.meta.sample_meta_description = 'Altered'; },
    packet => { packet.simulationExecution.tools[1].pages[0].provider_record.published = true; },
    packet => { packet.simulationExecution.tools[2].operations.pop(); },
    packet => { packet.simulationExecution.tools[3].pages[0].content_blocks[0].body = 'Altered visible copy'; },
    packet => { packet.simulationExecution.receipts[0].input_sha256 = createHash('sha256').update('different').digest('hex'); },
    packet => { packet.simulationExecution.approval.content_sha256 = 'changed'; },
    packet => { packet.simulationExecution.tools[0].protected_live_after[0].original.excerpt = 'Changed'; },
    packet => { packet.pages[0].approval.status = 'approved'; },
  ];
  for (const mutate of mutations) {
    const changed = structuredClone(original); mutate(changed);
    await assert.rejects(verifyWebsiteSimulation(changed));
  }
  await assert.rejects(stageWebsiteSimulation(original), /staging the same run twice/);
  const fresh = await execute();
  assert.notEqual(fresh.simulationExecution.id, original.simulationExecution.id);
});
