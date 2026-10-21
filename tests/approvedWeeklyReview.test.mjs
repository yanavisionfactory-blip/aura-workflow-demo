import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'vite';
import { APPROVED_WEEKLY_PREFIX, approvedWeeklyRequest, approvedWeeklyMarkdown, weeklyCsvTemplate, weeklyPeriods, WEEKLY_PLATFORMS } from '../src/lib/weeklyReviewIntake.mjs';
import { totals } from '../src/lib/weeklyAccountReview.mjs';
import { testWeeklyPacket } from './fixtures/approvedWeeklyPacket.mjs';
import { primaryResultFromOutputs } from '../src/lib/resultPresentation.mjs';

const repo = fileURLToPath(new URL('../', import.meta.url));
let temporary, renderSetup, renderResult;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, '.approved-weekly-render-'));
  await build({ configFile: path.join(repo, 'vite.config.js'), logLevel: 'silent', build: { ssr: path.join(repo, 'tests/fixtures/approvedWeeklyRender.jsx'), outDir: temporary, emptyOutDir: true, rollupOptions: { output: { entryFileNames: 'render.mjs' } } }, ssr: { noExternal: ['lucide-react'] } });
  ({ renderSetup, renderResult } = await import(pathToFileURL(path.join(temporary, 'render.mjs'))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });

function intake() {
  const packet = testWeeklyPacket();
  return { config: { ...packet, client: { ...packet.client, name: 'Test unicode Å' } }, sources: { microsoft: { ...packet.sources[0], csv_text: 'id,period,campaign,impressions,clicks,spend,conversions,revenue\ntest-prev,previous,Test,1000,100,100,4,\ntest-now,current,Test,1000,100,200,4,' } } };
}

test('approved input form lists all named platforms without inventing scope or a destination', () => {
  const html = renderSetup();
  for (const name of WEEKLY_PLATFORMS.map((item) => item.name)) assert.ok(html.includes(name));
  assert.match(html, /Approved exports can be used without connecting an app/);
  assert.match(html, /Destination unconfirmed/);
  assert.match(html, /brand approval reference/);
  assert.match(html, /Export extraction|export extraction/);
  assert.doesNotMatch(html, /Northline Home|checked=""/);
});

test('input transport is compact, UTF-8 lossless, scoped and excludes prepared outputs', () => {
  const { config, sources } = intake();
  const result = approvedWeeklyRequest(config, sources);
  assert.ok(result.prompt.startsWith(APPROVED_WEEKLY_PREFIX));
  assert.ok(result.prompt.length < 20000);
  assert.deepEqual(result.resources.tools, []);
  const packet = JSON.parse(Buffer.from(result.resources.documents[0].file_url.split(',')[1], 'base64').toString('utf8'));
  assert.equal(packet.config.client.name, 'Test unicode Å');
  assert.equal(packet.sources.length, 1);
  assert.equal(packet.sources[0].source_key, 'microsoft');
  assert.equal(packet.sources[0].input_kind, 'approved_export');
  assert.equal('experiments' in packet, false);
  for (const key of ['experiments', 'creatives', 'backlog', 'findings', 'sources', 'summary', 'execution']) assert.equal(key in packet.config, false, key);
});

test('blank templates never contain fabricated metrics and use defined conversions', () => {
  for (const platform of WEEKLY_PLATFORMS) {
    const template = weeklyCsvTemplate(platform.key);
    assert.match(template, /conversions,revenue/);
    assert.doesNotMatch(template, /SIMULATED|Northline/);
    assert.equal(template.split('\r\n')[1].split(',').slice(3).every((cell) => cell === ''), true);
  }
});

test('invalid approvals, source definitions and reporting confirmations remain blocked', () => {
  const { config, sources } = intake();
  config.scope.confirmed = false;
  assert.throws(() => approvedWeeklyRequest(config, sources), /Confirm/);
  config.scope.confirmed = true;
  delete sources.microsoft.accountId;
  assert.throws(() => approvedWeeklyRequest(config, sources), /account and metric/);
  sources.microsoft.accountId = 'TEST';
  config.reporting.confirmed = true;
  assert.throws(() => approvedWeeklyRequest(config, sources), /reporting confirmation/);
});

test('real calendar cutoffs, missing value and period labels do not use the sample assumptions', () => {
  assert.deepEqual(weeklyPeriods('2026-09-20').current, { from: '2026-09-14', to: '2026-09-20', label: '2026-09-14 – 2026-09-20' });
  assert.throws(() => weeklyPeriods('2026-02-30'), /valid calendar/);
  const packet = testWeeklyPacket();
  assert.equal(totals(packet.sources[0], 'current').revenue, null);
  assert.equal(totals(packet.sources[0], 'current').roas, null);
  const summary = renderResult(packet);
  assert.match(summary, /€50\.00/);
  assert.match(summary, /Unavailable/);
  assert.match(summary, /HANDOFF BLOCKER/);
  const source = renderResult(packet, 'Sources');
  assert.match(source, /2026-09-14/);
  assert.match(source, /UNIT-TEST-ACCOUNT/);
  assert.match(source, /qualified lead credit/);
  assert.doesNotMatch(source, /Northline|12–18 Oct|Purchase credits/);
});

test('all experiment, creative and backlog details are rendered and included in the download', () => {
  const packet = testWeeklyPacket(), markdown = approvedWeeklyMarkdown(packet);
  for (const section of ['Summary', 'Experiments', 'Draft variants', 'Backlog', 'Sources']) assert.ok(renderResult(packet, section).includes('Download full review'));
  for (const experiment of packet.experiments) {
    assert.ok(renderResult(packet, 'Experiments').includes(experiment.title));
    assert.ok(markdown.includes(experiment.decision));
  }
  for (const item of packet.backlog) assert.ok(markdown.includes(item.acceptance));
  assert.match(markdown, /test-prev, test-now/);
  assert.match(markdown, /UNCONFIRMED/);
  assert.match(markdown, /SHA-256/);
});

test('saved approved packets select the native result only with actual accepted execution checks', () => {
  const packet = testWeeklyPacket();
  const output = { operation: 'weekly.review.prepare', status: 'completed', critic: { action: 'accept' }, outcome_check: { status: 'verified' }, provider_result: { kind: 'weekly_review', synthetic: false, packet } };
  assert.equal(primaryResultFromOutputs([output])?.kind, 'weekly_review');
  output.critic.action = 'reject';
  assert.notEqual(primaryResultFromOutputs([output])?.kind, 'weekly_review');
});

test('only explicitly scoped Meta/Amazon scenarios can mix with approved exports', () => {
  const { config, sources } = intake();
  config.version = 2;
  config.scope.included.push('meta', 'amazon');
  config.scope.simulated = ['meta', 'amazon'];
  assert.throws(() => approvedWeeklyRequest(config, sources), /Explicitly confirm/);
  config.scope.simulationConfirmed = true;
  const request = approvedWeeklyRequest(config, sources);
  const packet = JSON.parse(Buffer.from(request.resources.documents[0].file_url.split(',')[1], 'base64').toString('utf8'));
  assert.deepEqual(packet.sources.map(item => item.input_kind), ['approved_export', 'simulated_scenario', 'simulated_scenario']);
  for (const source of packet.sources.slice(1)) {
    assert.match(source.csv_text, /SIMULATED/);
    assert.match(source.metadata.filename, /^SIMULATED_/);
    assert.equal(source.metadata.currency, 'EUR');
    assert.equal(source.periods.current.to, config.periods.current.to);
    assert.equal(source.metadata.approvedBy, undefined);
  }
  config.scope.simulated.push('microsoft');
  assert.throws(() => approvedWeeklyRequest(config, sources), /Explicitly confirm/);
});

test('mixed saved results and every download section retain simulation labels', () => {
  const packet = testWeeklyPacket();
  packet.version = 2; packet.provenance = 'mixed_evidence';
  packet.execution.mode = 'backend_executed_mixed_evidence';
  packet.sources[0].provenance = 'simulated';
  packet.sources[0].simulationNotice = 'SIMULATED authored sample, no client results';
  packet.findings.forEach(item => { item.provenance = 'simulated'; });
  [...packet.experiments, ...packet.creatives, ...packet.backlog].forEach(item => { item.simulationBased = true; });
  const output = { operation: 'weekly.review.prepare', status: 'completed', critic: { action: 'accept' }, outcome_check: { status: 'verified' }, provider_result: { kind: 'weekly_review', synthetic: true, packet } };
  assert.equal(primaryResultFromOutputs([output])?.kind, 'weekly_review');
  for (const section of ['Summary', 'Experiments', 'Draft variants', 'Backlog', 'Sources']) {
    assert.match(renderResult(packet, section), /SIMULAT/);
    assert.doesNotMatch(renderResult(packet, section), /Approved by Unit test/);
  }
  const markdown = approvedWeeklyMarkdown(packet);
  assert.match(markdown, /SIMULATED SCENARIOS INCLUDED/);
  assert.equal((markdown.match(/SIMULATION-BASED/g) || []).length, 12);
  assert.doesNotMatch(markdown, /approved by Unit test/);
});
