import test from 'node:test';
import assert from 'node:assert/strict';
import packet from '../src/showcase/weekly-account-review/data.mjs';
import { checks, evidenceRows, ratio, reviewModel, sourceCsv, syntheticWeeklyRequest, totals, validatePacket } from '../src/lib/weeklyAccountReview.mjs';
import { executionSteps, originalPrompt, workflowSteps } from '../src/showcase/weekly-account-review/scenario.mjs';

test('real workflow inputs contain source bytes and brief, never prewritten outcome drafts', () => {
  const prompt = syntheticWeeklyRequest(packet);
  assert.ok(prompt.startsWith('AURA_WEEKLY_REVIEW_V1\n'));
  const request = JSON.parse(prompt.slice(prompt.indexOf('\n') + 1));
  assert.equal(request.sources.length, 3);
  assert.equal(request.config.client.fictional, true);
  for (const key of ['experiments', 'creatives', 'backlog', 'execution', 'summary']) assert.equal(key in request.config, false);
  for (const source of request.sources) {
    assert.equal('rows' in source.metadata, false);
    assert.match(source.csv_text, /SIMULATED/);
  }
});

test('weekly review calculates weighted platform metrics and never creates a blended revenue total', () => {
  assert.deepEqual(validatePacket(packet), []);
  const model = reviewModel(packet);
  assert.equal(model.paidSpend, 5130);
  assert.equal(model.paidSpendPrevious, 4300);
  assert.equal(model.platforms.find((item) => item.source.key === 'google').current.revenue, 10800);
  assert.equal(model.platforms.find((item) => item.source.key === 'meta').current.revenue, 7000);
  const email = model.platforms.find((item) => item.source.key === 'klaviyo').current;
  assert.equal(email.revenue, 12400);
  assert.equal(email.delivered, 18000);
  assert.equal(email.uniqueClicks, 584);
  assert.equal(email.clickRate, 584 / 18000);
  assert.equal('revenue' in model, false);
  assert.equal('roas' in model, false);
  assert.equal('uniqueOrders' in model, false);
  assert.equal(ratio(5, 0), null);
});

test('material weekly changes resolve to source rows and remain descriptive', () => {
  const model = reviewModel(packet);
  assert.deepEqual(model.findings.map((item) => [item.id, item.current, item.previous, item.change]), [['F1', 50, 25, 1], ['F2', 60, 25, 1.4], ['F3', 0.012, 0.024, -0.5]]);
  assert.equal(model.findings.every((item) => item.material), true);
  for (const finding of model.findings) assert.equal(evidenceRows(packet, finding.evidence).some((item) => item.missing), false);
  const current = evidenceRows(packet, ['Q-C-GENERIC'])[0].row;
  const campaign = evidenceRows(packet, ['G-C-NONBRAND'])[0].row;
  assert.equal(current.spend / campaign.spend, 0.375);
  assert.equal(packet.expertChecks.some((item) => /not statistically significant/.test(item)), true);
});

test('report validation rejects mismatched periods, currencies, timezones, cutoffs and scope', () => {
  for (const [field, value] of [['currency', 'EUR'], ['timezone', 'UTC'], ['asOf', '2026-10-21T06:00:00Z']]) {
    const copy = structuredClone(packet); copy.sources[0][field] = value;
    assert.ok(validatePacket(copy).some((error) => /does not align/.test(error)));
  }
  const gap = structuredClone(packet); gap.periods.current.from = '2026-10-13';
  assert.ok(validatePacket(gap).length);
  const scope = structuredClone(packet); scope.sources.push({ ...structuredClone(packet.sources[0]), key: 'microsoft' });
  assert.ok(validatePacket(scope).some((error) => /outside the selected scope/.test(error)));
});

test('bad evidence, impossible denominators and executed proposals cannot pass the review', () => {
  const invalid = structuredClone(packet);
  invalid.sources[0].rows[0].clicks = 100000;
  invalid.experiments[0].evidence = ['UNKNOWN'];
  invalid.experiments[1].status = 'executed';
  const errors = validatePacket(invalid);
  assert.ok(errors.some((error) => /Invalid denominator/.test(error)));
  assert.ok(errors.some((error) => /Unresolved evidence/.test(error)));
  assert.ok(errors.some((error) => /cannot be marked executed/.test(error)));
});

test('exactly three proposed tests have evidence, decision rules, guardrails and feasibility gates', () => {
  assert.equal(packet.experiments.length, 3);
  for (const item of packet.experiments) {
    assert.ok(item.evidence.length >= 2);
    for (const field of ['hypothesis', 'change', 'design', 'primary', 'guardrails', 'decision', 'feasibility']) assert.ok(item[field].length > 20, `${item.id} needs ${field}`);
    assert.equal(item.status, 'proposed');
    for (const dependency of item.dependencies) assert.ok(packet.backlog.some((task) => task.id === dependency));
  }
  const extra = structuredClone(packet); extra.experiments.push(structuredClone(extra.experiments[0]));
  assert.ok(validatePacket(extra).some((error) => /Exactly three/.test(error)));
});

test('six draft variants respect Google text limits and email isolates the subject line', () => {
  assert.equal(packet.creatives.flatMap((item) => item.variants).length, 6);
  const bad = structuredClone(packet); bad.creatives[0].variants[0].headlines[0] = 'x'.repeat(31);
  assert.ok(validatePacket(bad).some((error) => /character limits/.test(error)));
  const email = packet.creatives.find((item) => item.source === 'klaviyo');
  assert.equal(email.variants.every((item) => Object.keys(item).sort().join(',') === 'label,subject'), true);
  assert.ok(email.shared.body);
  assert.notEqual(email.variants[0].subject, email.variants[1].subject);
});

test('sample exports preserve reporting definitions and identify query breakdowns to prevent double counting', () => {
  const csv = sourceCsv(packet, 'google');
  assert.match(csv, /SIMULATED/);
  assert.match(csv, /G-C-NONBRAND/);
  assert.match(csv, /nonbrand_search_term_breakdown_do_not_add_to_campaigns/);
  assert.match(csv, /America\/Chicago/);
  assert.match(csv, /30-day click/);
  assert.match(csv, /2026-10-12/);
  assert.throws(() => sourceCsv(packet, 'hubspot'), /outside/);
  assert.equal(totals(packet.sources[0], 'current').spend, 2880);
});

test('real-client and reporting gaps stay open, and every playback step is read-only', () => {
  assert.equal(packet.client.fictional, true);
  assert.equal(packet.client.engagementConfirmed, false);
  assert.equal(packet.reporting.confirmed, false);
  assert.equal(packet.reporting.destinationUrl, null);
  assert.equal(checks(packet).filter((item) => item.status === 'review').length, 3);
  assert.equal(workflowSteps.every((item) => item.riskLevel === 'read'), true);
  assert.equal(executionSteps(0).filter((item) => item.status === 'running').length, 1);
  assert.equal(executionSteps(6).every((item) => item.status === 'completed'), true);
  assert.match(originalPrompt, /Do not launch campaigns, change budgets or send messages/);
  assert.match(originalPrompt, /Use only the platforms included in this client’s scope/);
  assert.doesNotMatch(JSON.stringify(packet), /workspace_id|oauth_access_token|api_key|refresh_token|data:text\/csv/i);
});
