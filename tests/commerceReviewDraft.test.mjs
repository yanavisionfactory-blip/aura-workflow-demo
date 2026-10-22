import test from 'node:test';
import assert from 'node:assert/strict';
import { executeCommerceSimulation, validateCommercePacket } from '../src/lib/commerceSimulation.mjs';
import { checkedReviewCopy, clearReviewCopy, editCopy, loadReviewCopy, saveReviewCopy, withReviewCopy } from '../src/showcase/commerce-workflow/reviewDraft.mjs';
import { simulateCopyRevision } from '../src/showcase/commerce-workflow/simulatedCopyEdit.mjs';

test('manual copy edits carry into the draft while source evidence remains immutable', async () => {
  const packet = await executeCommerceSimulation();
  const updated = editCopy(packet.copy, 'meta.headline', 'Your Reusable Everyday Mug');
  const reviewed = withReviewCopy(packet, updated);
  assert.equal(reviewed.copy.meta.headline, 'Your Reusable Everyday Mug');
  assert.equal(reviewed.reviewEdited, true);
  assert.equal(reviewed.sources, packet.sources);
  assert.equal(reviewed.tests, packet.tests);
  assert.notEqual(packet.copy.meta.headline, reviewed.copy.meta.headline);
  assert.equal(await validateCommercePacket(packet), true);
  assert.equal(withReviewCopy(packet, packet.copy), packet);
});
test('only complete bounded copy can persist, and corrupt browser storage falls back to the original scenario', async () => {
  const { copy } = await executeCommerceSimulation();
  const values = new Map(), storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  saveReviewCopy(storage, copy);
  assert.deepEqual(loadReviewCopy(storage), copy);
  assert.throws(() => checkedReviewCopy(editCopy(copy, 'google.headlines.0', 'x'.repeat(31))), /1–30/);
  assert.throws(() => checkedReviewCopy(editCopy(copy, 'meta.primary.0', '')), /1–1500/);
  clearReviewCopy(storage);
  assert.equal(loadReviewCopy(storage), null);
  storage.setItem('aura-commerce-review-copy-v1', '{broken');
  assert.equal(loadReviewCopy(storage), null);
});

test('simulated AI revisions obey channel limits and preserve every unselected channel and source', async () => {
  const packet = await executeCommerceSimulation();
  const original = structuredClone(packet.copy);
  for (const channel of ['meta', 'google', 'seller']) for (const prompt of ['Make it shorter', 'More conversational', 'Lead with 16 oz']) {
    const result = simulateCopyRevision(packet.copy, channel, prompt);
    assert.equal(result.mode, 'simulated-ai');
    assert.ok(result.changedPaths.length > 0);
    assert.ok(result.changedPaths.every(path => path.startsWith(channel + '.')));
    assert.deepEqual(checkedReviewCopy(result.copy), result.copy);
    for (const other of ['meta', 'google', 'seller'].filter(key => key !== channel)) assert.deepEqual(result.copy[other], original[other]);
    assert.equal(result.copy.message, original.message);
  }
  assert.deepEqual(packet.copy, original);
  assert.equal(await validateCommercePacket(packet), true);
});

test('quoted headline replacements apply exactly and unsupported prompts produce no fabricated success', async () => {
  const { copy } = await executeCommerceSimulation();
  const result = simulateCopyRevision(copy, 'meta', 'Change the headline to "Your Everyday Coffee Mug"');
  assert.equal(result.copy.meta.headline, 'Your Everyday Coffee Mug');
  assert.deepEqual(result.changedPaths, ['meta.headline']);
  assert.throws(() => simulateCopyRevision(copy, 'google', 'Change the headline to "' + 'x'.repeat(31) + '"'), /1–30/);
  assert.throws(() => simulateCopyRevision(copy, 'meta', 'Invent an unknown product benefit'), /simulated AI editor/);
  assert.throws(() => simulateCopyRevision(copy, 'amazon', 'Make it shorter'), /Choose a Meta ad/);
});
