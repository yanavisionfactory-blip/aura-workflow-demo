import test from 'node:test';
import assert from 'node:assert/strict';
import { executeCommerceSimulation, validateCommercePacket } from '../src/lib/commerceSimulation.mjs';
import { checkedReviewCopy, clearReviewCopy, editCopy, loadReviewCopy, saveReviewCopy, withReviewCopy } from '../src/showcase/commerce-workflow/reviewDraft.mjs';

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
