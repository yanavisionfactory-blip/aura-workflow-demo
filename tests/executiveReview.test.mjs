import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'vite';
import { findEvidence, formatChange, formatValue, metricLabel, toolNames } from '../src/lib/executiveReview.mjs';
import { primaryResultFromOutputs } from '../src/lib/resultPresentation.mjs';
import { operationStepTitle } from '../src/lib/planPresentation.mjs';

const repo = fileURLToPath(new URL('../', import.meta.url));
const request = JSON.parse(fs.readFileSync(path.join(repo, 'examples/executive-review/request.json'), 'utf8'));
// Rendering-only test data. Arithmetic and actual dispatcher receipts are tested in Python.
const sources = request.sources.map((input) => {
  const [header, ...lines] = input.csv_text.trim().split('\n');
  const fields = header.split(',');
  const rows = lines.map((line, index) => ({ ...Object.fromEntries(line.split(',').map((value, i) => [fields[i], fields[i] === 'value' ? Number(value) : value])), csv_row: index + 2 }));
  return { ...input, input, name: toolNames[input.source_key], rows, receipt: { id: `test-only-${input.source_key}`, executor: 'AURA biweekly export processor', executed_at: '2026-10-20T15:00:00Z', input_sha256: 'a'.repeat(64), input_rows: rows.length, input_bytes: input.csv_text.length, provider_api_called: false } };
});
const refs = sources.map((source) => source.rows[0].id);
const performance = sources.map((source) => ({ id: `${source.source_key}:example`, source: source.source_key, tool: source.name, metric: source.rows[0].metric, current: 12, previous: 10, target: null, delta: 2, change: .2, target_variance: null, unit: 'count', headline: true, evidence: [source.rows[0].id] }));
performance.push({ ...performance[6], id: 'crm:leads', metric: 'leads', current: 60, previous: 50 });
const packet = { config: request.config, periods: request.sources[0].periods, synthetic: true, sources, performance,
  execution: { id: 'rendering-only-review-receipt', mode: 'backend_executed_synthetic', source_operations: 10, model_call_executed: true, model: 'rendering-test-model', executed_at: '2026-10-20T15:00:00Z', provider_api_called: false },
  narrative: { summary: 'Illustrative summary from the executed review packet.', observations: [{ title: 'Observed sample result', detail: 'A source-backed observation.', evidence: [refs[6]] }], hypotheses: [{ title: 'Possible explanation', detail: 'A hypothesis to validate.', evidence: [refs[7]] }], actions: [{ id: 'A1', tool: 'crm', priority: 'P1', title: 'Validate qualification', owner: 'Proposed CRM lead', due: '2026-10-23', status: 'proposed', acceptance: 'Record agreed definitions.', dependencies: [], evidence: [refs[6]] }] },
  agenda: [{ minutes: '0–5', topic: 'Executive priorities', decision: 'Review scenario target gaps.' }] };
let temporary, render;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, '.executive-render-'));
  await build({ configFile: path.join(repo, 'vite.config.js'), logLevel: 'silent', build: { ssr: path.join(repo, 'tests/fixtures/executiveReviewRender.jsx'), outDir: temporary, emptyOutDir: true, rollupOptions: { output: { entryFileNames: 'render.mjs' } } }, ssr: { noExternal: ['lucide-react'] } });
  ({ render } = await import(pathToFileURL(path.join(temporary, 'render.mjs'))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });

test('executive review is a verified native AURA primary result with ten tool outputs', () => {
  const output = { step_key: 'review', operation: 'executive.review.prepare', critic: { action: 'accept' }, outcome_check: { status: 'verified' }, provider_result: { kind: 'executive_review', synthetic: true, packet } };
  assert.equal(primaryResultFromOutputs([output], {}, { primary_step_key: 'review' }).kind, 'executive_review');
  for (const mutate of [
    (value) => { value.critic.action = 'escalate'; },
    (value) => { value.outcome_check.status = 'pending'; },
    (value) => { value.provider_result.packet.execution.mode = 'static_playback'; },
    (value) => { value.provider_result.packet.sources.pop(); },
  ]) {
    const invalid = structuredClone(output); mutate(invalid);
    assert.notEqual(primaryResultFromOutputs([invalid], {}, { primary_step_key: 'review' }).kind, 'executive_review');
  }
});

test('overview leads with executive result and explicit real-client versus simulated-data labels', () => {
  const html = render(packet);
  for (const text of ['Goelzer Industries', 'REAL AURA RUN', 'ALL REVIEW DATA SIMULATED', 'Executive summary', 'Results per tool', 'Possible explanations', 'Vendor reporting APIs were not called']) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /Open in Google Docs|docs\.google\.com/);
  for (const name of Object.values(toolNames)) assert.ok(html.includes(`View ${name} result`));
});

test('every tool output renders separate retained rows, hash and truthful processing receipt', () => {
  for (const source of packet.sources) {
    const html = render(packet, { tab: 'Tool outputs', tool: source.source_key });
    for (const value of [source.metadata.filename, source.rows[0].id, source.receipt.id, 'Input SHA-256', 'Vendor reporting API was not called', 'Actual client product:', 'unconfirmed', 'Download simulated source CSV']) assert.ok(html.includes(value), value);
  }
  assert.equal(findEvidence(packet, refs[1]).source.source_key, 'google_business_profile');
  assert.equal(findEvidence(packet, 'not-real'), null);
});

test('meeting agenda, actions and sources retain required distinctions and source context', () => {
  const agenda = render(packet, { tab: 'Meeting agenda' });
  assert.match(agenda, /No meeting has been scheduled/);
  assert.match(agenda, /Previous review · simulated context/);
  const actions = render(packet, { tab: 'Action register' });
  assert.match(actions, /Proposed CRM lead/); assert.match(actions, /2026-10-23/); assert.match(actions, /not assigned/);
  const context = render(packet, { tab: 'Sources and definitions' });
  assert.match(context, /lucemedia.net\/commercial-printer-success-story/);
  assert.match(context, /actual product unconfirmed/);
  assert.match(context, /no unmatched cohort conversion rates/);
  assert.match(context, /Download full review and retained evidence/);
  assert.match(render(packet, { tab: 'Performance' }), /Simulated performance and target comparison/);
});

test('formatting and plan labels use truthful metrics and actual operation semantics', () => {
  assert.equal(formatValue(null), 'N/A'); assert.equal(formatValue(.025, 'rate'), '2.50%');
  assert.equal(formatChange({ unit: 'rate', delta: .01 }), '+1.00 pp');
  assert.equal(formatChange({ unit: 'count', change: null }), 'N/A');
  assert.match(metricLabel('tracked_lead_credits'), /not unique leads/);
  assert.equal(operationStepTitle({ operation: 'executive.source.analyze', arguments: { source_key: 'instagram' } }), 'Process the simulated Instagram export');
});
