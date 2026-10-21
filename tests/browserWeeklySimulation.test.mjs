import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { browserSimulationInputs, parseSimulationSource, runBrowserWeeklySimulation, verifySavedBrowserSimulation, validateBrowserSimulation } from '../src/lib/browserWeeklySimulation.mjs';
import { approvedWeeklyMarkdown } from '../src/lib/weeklyReviewIntake.mjs';

const now = new Date('2026-10-20T06:00:00Z');
test('browser run processes seven sources, retains real hashes and validates all eight steps', async () => {
  const steps = [];
  const packet = await runBrowserWeeklySimulation({ now, onStep: step => steps.push(step) });
  assert.equal(steps.filter(step => step.status === 'completed').length, 8);
  assert.equal(packet.sources.length, 7);
  assert.equal(packet.findings.length, 32);
  assert.equal(packet.experiments.length, 3);
  assert.equal(packet.creatives.flatMap(item => item.variants).length, 6);
  assert.equal(packet.backlog.length, 9);
  assert.deepEqual(validateBrowserSimulation(packet), []);
  assert.equal(packet.execution.model_call_executed, false);
  assert.equal(packet.execution.provider_api_called, false);
  assert.equal(packet.execution.external_writes, false);
  assert.equal(packet.execution.mode, 'browser_executed_simulation');
  for (const source of packet.sources) {
    assert.equal(source.execution.input_sha256, createHash('sha256').update(source.inputCsv).digest('hex'));
    assert.equal(source.rows.length, 2);
  }
  const find = (source, metric) => packet.findings.find(item => item.source === source && item.metric === metric);
  assert.equal(find('google', 'cpa').previous, 60);
  assert.equal(find('google', 'cpa').current, 80);
  assert.equal(find('meta', 'cpa').current, 42);
  assert.equal(find('amazon', 'roas').current, 3);
  assert.equal(find('klaviyo', 'clickRate').current, .035);
  assert.equal(find('microsoft', 'cpa').material, true); // -20% including floating-point tolerance
  assert.equal(find('meta', 'ctr').material, true);
  assert.equal(find('hubspot', 'clickRate').current, .02);
  assert.deepEqual(await verifySavedBrowserSimulation(JSON.parse(JSON.stringify(packet))), packet);
  const markdown = approvedWeeklyMarkdown(packet);
  assert.match(markdown, /browser_executed_simulation/);
  assert.match(markdown, /runtime model called: false/);
  assert.match(markdown, /SIMULATED/);
  assert.ok(!markdown.includes('Model drafting executed'));
});

test('browser route cannot relabel real input or accept altered authored sample values', async () => {
  const inputs = browserSimulationInputs(now);
  inputs.sources[0].input_kind = 'approved_export';
  assert.throws(() => parseSimulationSource(inputs.sources[0], inputs.config), /sample inputs only/);
  await assert.rejects(runBrowserWeeklySimulation({ now, inputs }), /authored seven-platform sample only/);
  const changed = browserSimulationInputs(now);
  changed.sources[0].csv_text = changed.sources[0].csv_text.replace('5400', '5000');
  await assert.rejects(runBrowserWeeklySimulation({ now, inputs: changed }), /authored seven-platform sample only/);
});

test('parser rejects invalid denominators and saved evidence/metrics tampering', async () => {
  const inputs = browserSimulationInputs(now);
  inputs.sources[0].csv_text = inputs.sources[0].csv_text.replace('120000,3600', '100,3600');
  assert.throws(() => parseSimulationSource(inputs.sources[0], inputs.config), /invalid metric denominator/);
  const packet = await runBrowserWeeklySimulation({ now });
  packet.sources[0].rows[0].spend = 1;
  await assert.rejects(verifySavedBrowserSimulation(packet), /metrics do not match/);
});

test('saved results reject cross-source proposal references and cyclic backlog dependencies', async () => {
  const packet = await runBrowserWeeklySimulation({ now });
  packet.experiments[0].evidence = ['SIM-meta-current'];
  assert.ok(validateBrowserSimulation(packet).some(error => error.includes('Cross-source')));
  packet.backlog[0].dependencies = ['B2'];
  assert.ok(validateBrowserSimulation(packet).some(error => error.includes('Cyclic')));
});
