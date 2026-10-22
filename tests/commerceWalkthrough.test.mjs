import test from 'node:test';
import assert from 'node:assert/strict';
import { initialScene, sceneUrl } from '../src/showcase/commerce-workflow/walkthrough.mjs';

test('walkthrough deep links survive refresh and reject invalid scene values', () => {
  assert.equal(initialScene('?screen=results'), 4);
  for (let i = 0; i < 5; i++) assert.equal(initialScene(`?scene=${i}`), i);
  for (const value of ['-1', '5', '0.5', 'NaN', '1e9']) assert.equal(initialScene(`?scene=${value}`), 0);
});
test('shareable scene URLs preserve the separate demo path and clear stale parameters', () => {
  const current = 'https://demo.example/showcase/commerce-workflow/?scene=1&stale=1#old';
  assert.equal(sceneUrl(4, current), '/showcase/commerce-workflow/?screen=results');
  assert.equal(sceneUrl(0, current), '/showcase/commerce-workflow/?scene=0');
  assert.equal(initialScene(new URL(sceneUrl(2, current), current).search), 2);
});
