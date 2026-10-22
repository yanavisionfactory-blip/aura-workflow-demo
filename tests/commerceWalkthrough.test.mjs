import test from 'node:test';
import assert from 'node:assert/strict';
import { initialScene, sceneUrl } from '../src/showcase/commerce-workflow/walkthrough.mjs';
import { TOOL_PAGES, toolHref, evidenceHref, readToolRoute } from '../src/showcase/commerce-workflow/toolNavigation.mjs';
import { simulationInputs } from '../src/lib/commerceSimulation.mjs';

test('walkthrough deep links survive refresh and reject invalid scene values', () => {
  assert.equal(initialScene('?screen=results'), 4);
  for (let i = 0; i < 5; i++) assert.equal(initialScene(`?scene=${i}`), i);
  for (const value of ['-1', '5', '0.5', 'NaN', '1e9']) assert.equal(initialScene(`?scene=${value}`), 0);
});
test('every view-in-tool destination survives refresh in the separate demo', () => {
  for (const [tool, config] of Object.entries(TOOL_PAGES)) for (const [view] of config.pages) {
    assert.deepEqual(readToolRoute(toolHref(tool, view)), {tool, view, evidence:undefined});
  }
  assert.equal(readToolRoute('?tool=unknown'), null);
  assert.equal(readToolRoute('?tool=__proto__'), null);
  assert.equal(readToolRoute('?tool=google&view=https://outside.example').view, 'ads');
  assert.equal(readToolRoute('?tool=meta&evidence=G-Q-C-2').evidence, undefined);
  assert.throws(() => toolHref('google','missing'));
});
test('all evidence links resolve to the correct tool and report instead of a generic result modal', () => {
  for (const [tool, source] of Object.entries(simulationInputs())) for (const row of [...source.rows, ...(source.listing ? [source.listing] : [])]) {
    const route = readToolRoute(evidenceHref(row.id));
    assert.equal(route.tool, tool);
    assert.equal(route.evidence, row.id);
    assert.equal(route.view, row.id === 'S-STOCK' ? 'inventory' : tool === 'seller' ? 'business' : tool === 'meta' ? 'performance' : row.report === 'search_terms' ? 'search-terms' : 'campaigns');
  }
});
test('shareable scene URLs preserve the separate demo path and clear stale parameters', () => {
  const current = 'https://demo.example/showcase/commerce-workflow/?scene=1&stale=1#old';
  assert.equal(sceneUrl(4, current), '/showcase/commerce-workflow/?screen=results');
  assert.equal(sceneUrl(0, current), '/showcase/commerce-workflow/?scene=0');
  assert.equal(initialScene(new URL(sceneUrl(2, current), current).search), 2);
});
