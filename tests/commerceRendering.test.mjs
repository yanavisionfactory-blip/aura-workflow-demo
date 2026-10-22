import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'vite';
import { executeCommerceSimulation } from '../src/lib/commerceSimulation.mjs';
let temporary, render;
const repo = fileURLToPath(new URL('../', import.meta.url));
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, '.commerce-render-'));
  await build({ configFile: path.join(repo, 'vite.commerce.config.js'), logLevel: 'silent', build: { ssr: path.join(repo, 'tests/fixtures/commerceRender.jsx'), outDir: temporary, emptyOutDir: true, rollupOptions: { output: { entryFileNames: 'render.mjs' } } }, ssr: { noExternal: ['lucide-react'] } });
  ({ render } = await import(pathToFileURL(path.join(temporary, 'render.mjs'))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });
test('complete review renders all requested tools, tests, copy, source tabs and approvals', async () => {
  const packet = await executeCommerceSimulation();
  const html = render(packet);
  for (const text of ['Your weekly marketing action package', 'Inventory needs attention', 'Google Ads', 'Meta Ads Manager', 'Amazon Ads', 'Amazon Seller Central', 'Three revised listing bullets', 'Approval required:', 'Website total purchases:', 'unavailable', 'no causal or statistical-significance claim', 'S-STOCK']) assert.ok(html.includes(text), text);
  for (const test of packet.tests) assert.ok(html.includes(test.title));
  for (const copy of [...packet.copy.google.headlines, ...packet.copy.meta.primary, ...packet.copy.seller.bullets]) assert.ok(html.includes(copy.replaceAll('&', '&amp;')));
  assert.equal((html.match(/role="tab"/g) || []).length, 4);
  assert.match(html, /id="evidence-S-C"/);
  assert.match(html, /href="#evidence-G-C-N"/);
  assert.doesNotMatch(html, /launch now|publish now|Update Gmail/i);
  assert.match(render(await executeCommerceSimulation('ready')), /Scenario stock gate passed; manager approval pending/);
});
