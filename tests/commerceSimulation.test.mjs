import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { BRIEF, TOOLS, commerceMarkdown, executeCommerceSimulation, executeTool, simulationInputs, validateCommercePacket } from '../src/lib/commerceSimulation.mjs';

test('four actual simulation processors run with Seller readiness first and source hashes', async () => {
  const sequence = [], packet = await executeCommerceSimulation('low', key => sequence.push(key));
  assert.deepEqual(sequence, ['seller', 'google', 'meta', 'amazon']);
  assert.equal(packet.execution.completed_steps, 5);
  assert.equal(packet.execution.provider_api_called, false);
  assert.equal(packet.execution.model_call_executed, false);
  assert.equal(packet.execution.external_writes, false);
  assert.equal(packet.sources.google.comparison.current.spend, 3298);
  assert.equal(packet.sources.google.comparison.current.purchases, 110);
  assert.equal(packet.sources.meta.comparison.current.clicks, 1700);
  assert.equal(packet.sources.meta.comparison.current.purchases, 74);
  assert.equal(packet.sources.amazon.comparison.current.sales, 6720);
  assert.equal(packet.sources.amazon.comparison.current.acos, 1750 / 6720);
  assert.equal(packet.sources.seller.comparison.current.sales, 9600);
  assert.equal(packet.sources.seller.comparison.current.unitSessionRate, .06);
  assert.equal(packet.websitePurchases, null);
  for (const key of Object.keys(TOOLS)) assert.match(packet.sources[key].receipt.input_sha256, /^[a-f0-9]{64}$/);
  assert.ok(Math.abs(packet.sources.seller.readiness.daysCover - .7) < .00001);
  assert.equal(packet.sources.seller.readiness.promotionReady, false);
  assert.match(packet.tests.find(item => item.source === 'amazon').approval, /HOLD/);
});

test('only available stock clears readiness; inbound/reserved and suppression do not', async () => {
  const ready = await executeCommerceSimulation('ready');
  assert.equal(ready.sources.seller.readiness.promotionReady, true);
  assert.equal(ready.sources.seller.readiness.daysCover, 21);
  const input = simulationInputs('low').seller;
  input.listing.inboundNotReceived = 10000;
  input.listing.reserved = 10000;
  assert.equal((await executeTool(input)).readiness.promotionReady, false);
  input.listing.available = 900;
  input.listing.suppressed = true;
  assert.equal((await executeTool(input)).readiness.promotionReady, false);
});

test('source dates, attribution, numeric values, IDs, ASIN and breakdown reconciliation are checked', async () => {
  const cases = [
    ['google', input => { input.currency = 'EUR'; }],
    ['meta', input => { input.definitions.attribution = 'silently changed'; }],
    ['google', input => { input.rows[0].spend = null; }],
    ['meta', input => { input.rows[1].id = input.rows[0].id; }],
    ['google', input => { input.rows.find(row => row.report === 'search_terms').spend += 1; }],
    ['seller', input => { input.listing.asin = 'unrelated'; }],
    ['seller', input => { input.rows[0].asin = 'unrelated'; }],
    ['seller', input => { input.listing.available = -1; }],
    ['amazon', input => { input.simulated = false; }],
  ];
  for (const [key, mutate] of cases) { const input = simulationInputs()[key]; mutate(input); await assert.rejects(() => executeTool(input)); }
  const meta = simulationInputs().meta;
  meta.rows.forEach(row => { row.purchases = 0; row.sales = 0; });
  const zero = await executeTool(meta);
  assert.equal(zero.comparison.current.cpa, null);
  assert.equal(zero.comparison.current.acos, null);
});

test('restored/exported results reject altered metrics, claims, readiness, receipts or evidence', async () => {
  const packet = await executeCommerceSimulation();
  await validateCommercePacket(JSON.parse(JSON.stringify(packet)));
  for (const mutate of [
    p => { p.sources.google.comparison.current.spend += 1; },
    p => { p.sources.seller.readiness.promotionReady = true; },
    p => { p.sources.meta.receipt.input_sha256 = 'invented'; },
    p => { p.copy.seller.title = 'Unapproved claim'; },
    p => { p.tests[0].evidence = ['NO-SOURCE']; },
    p => { p.execution.provider_api_called = true; },
    p => { p.websitePurchases = 184; },
  ]) { const altered = structuredClone(packet); mutate(altered); await assert.rejects(() => validateCommercePacket(altered)); }
});

test('review carries the complete requested copy, three tests and source-linked action register', async () => {
  const packet = await executeCommerceSimulation(), md = commerceMarkdown(packet);
  assert.equal(packet.tests.length, 3);
  assert.deepEqual(new Set(packet.tests.map(t => t.source)), new Set(['google', 'meta', 'amazon']));
  assert.equal(packet.copy.google.headlines.length, 2);
  assert.equal(packet.copy.meta.primary.length, 2);
  assert.equal(packet.copy.seller.bullets.length, 3);
  assert.equal(packet.checklist[0].priority, 'P0');
  for (const source of Object.values(packet.sources)) for (const row of source.rows) assert.ok(md.includes(`id="${row.id.toLowerCase()}"`));
  assert.match(md, /Website.*unavailable|Unavailable: no independent store orders export/);
  assert.match(md, /Do not add/);
  assert.match(md, /SIMULATED/);
  assert.ok(md.includes(BRIEF.asinNotice));
  assert.doesNotMatch(JSON.stringify(packet), /workspace_id|client_secret|access_token|@gmail\.com/);
  const entry = fs.readFileSync(new URL('../showcase/commerce-workflow/index.html', import.meta.url), 'utf8');
  assert.match(entry, /connect-src 'none'/);
});
