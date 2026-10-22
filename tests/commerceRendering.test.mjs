import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'vite';
import { executeCommerceSimulation } from '../src/lib/commerceSimulation.mjs';
import { TOOL_PAGES, readToolRoute, toolHref } from '../src/showcase/commerce-workflow/toolNavigation.mjs';
let temporary, render, renderWorkspace;
const repo = fileURLToPath(new URL('../', import.meta.url));
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, '.commerce-render-'));
  await build({ configFile: path.join(repo, 'vite.commerce.config.js'), logLevel: 'silent', build: { ssr: path.join(repo, 'tests/fixtures/commerceRender.jsx'), outDir: temporary, emptyOutDir: true, rollupOptions: { output: { entryFileNames: 'render.mjs' } } }, ssr: { noExternal: ['lucide-react'] } });
  ({ render, renderWorkspace } = await import(pathToFileURL(path.join(temporary, 'render.mjs'))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });
test('compact results retain all requested draft outputs and source-linked approvals', async () => {
  const packet = await executeCommerceSimulation();
  const html = render(packet);
  for (const text of ['Marketing action package ready', 'What happened', 'Tools used', 'changes published', '1 inventory issue needs attention', 'Google Ads', 'Meta Ads Manager', 'Amazon Ads', 'Amazon Seller Central', 'Three revised listing bullets', 'Approval required:', 'Website total purchases:', 'unavailable', 'no causal or statistical-significance claim', 'S-STOCK']) assert.ok(html.includes(text), text);
  for (const test of packet.tests) assert.ok(html.includes(test.title));
  for (const copy of [...packet.copy.google.headlines, ...packet.copy.meta.primary, ...packet.copy.seller.bullets]) assert.ok(html.includes(copy.replaceAll('&', '&amp;')));
  assert.equal((html.match(/class="ad-pill ad-cyan ad-tool-link"/g) || []).length, 4);
  for (const tool of Object.keys(TOOL_PAGES)) assert.ok(html.includes(toolHref(tool).replaceAll('&', '&amp;')));
  assert.match(html, /<section class="ad-main-output" aria-label="Main output: weekly marketing action package"/);
  const mainStart = html.indexOf('data-testid="main-output"');
  const firstDropdown = html.indexOf('<details');
  assert.ok(mainStart >= 0 && firstDropdown > mainStart, 'the main output precedes every dropdown');
  const mainOutput = html.slice(mainStart, firstDropdown);
  for (const text of [packet.copy.message, packet.copy.google.headlines[1], packet.copy.meta.headline, packet.copy.seller.title]) assert.ok(mainOutput.includes(text.replaceAll('&', '&amp;')));
  for (const tool of Object.keys(TOOL_PAGES)) assert.ok(mainOutput.includes(toolHref(tool).replaceAll('&', '&amp;')));
  assert.doesNotMatch(html, /<details[^>]*\sopen(?:=|\s|>)/, 'supporting details start collapsed');
  assert.match(html, /href="\?tool=google&amp;view=campaigns&amp;evidence=G-C-N"/);
  assert.doesNotMatch(html, /launch now|publish now|Update Gmail/i);
  assert.match(render(await executeCommerceSimulation('ready')), /Stock gate passed; approval pending/);
});
test('view-in-tool destinations show actual draft content with vendor-specific previews', async () => {
  const packet = await executeCommerceSimulation();
  const html = tool => renderWorkspace(packet, readToolRoute(toolHref(tool)));
  for (const tool of Object.keys(TOOL_PAGES)) {
    assert.ok(html(tool).includes('SIMULATED TOOL VIEW'));
    assert.ok(html(tool).includes('Back to AURA results'));
    assert.doesNotMatch(html(tool), /<form|action="https:\/\//);
  }
  for (const copy of packet.copy.google.headlines) assert.ok(html('google').includes(copy));
  assert.ok(html('google').includes('Search ad preview'));
  assert.ok(html('meta').includes(packet.copy.meta.primary[0].replaceAll('&', '&amp;')));
  assert.ok(html('meta').includes('Ad preview · Facebook Feed'));
  assert.ok(html('meta').includes('Creative storyboard'));
  assert.ok(html('amazon').includes('16 oz stainless steel travel mug'));
  assert.ok(html('amazon').includes('Needs approval'));
  assert.ok(html('amazon').includes('Promotion hold'));
  for (const text of [packet.copy.seller.title, ...packet.copy.seller.bullets]) assert.ok(html('seller').includes(text.replaceAll('&', '&amp;')));
  assert.ok(html('seller').includes('Product detail page preview'));
});
test('all report and source pages render, and evidence links highlight the matching source row', async () => {
  const packet = await executeCommerceSimulation();
  for (const [tool, config] of Object.entries(TOOL_PAGES)) for (const [view] of config.pages) {
    const html = renderWorkspace(packet, {tool, view});
    assert.ok(html.includes('No live account changes'), `${tool}/${view}`);
    assert.ok(html.includes(BRIEF_PRODUCT), `${tool}/${view}`);
  }
  const html = renderWorkspace(packet, readToolRoute('?tool=google&view=search-terms&evidence=G-Q-C-2'));
  assert.match(html, /id="evidence-G-Q-C-2" class="tw-row-selected"/);
  assert.ok(html.includes('16 oz travel mug'));
});
const BRIEF_PRODUCT = 'Everyday Travel Mug';
