import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'vite';

const repo = fileURLToPath(new URL('../', import.meta.url));
let temporary, renderSetup, renderResult;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, '.campaign-render-'));
  await build({ configFile: path.join(repo, 'vite.config.js'), logLevel: 'silent',
    build: { ssr: path.join(repo, 'tests/fixtures/campaignDraftRender.jsx'), outDir: temporary, emptyOutDir: true,
      rollupOptions: { output: { entryFileNames: 'render.mjs' } } }, ssr: { noExternal: ['lucide-react'] } });
  ({ renderSetup, renderResult } = await import(pathToFileURL(path.join(temporary, 'render.mjs'))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });

test('setup asks for a real audience and exact copy without claiming connected accounts', () => {
  const html = renderSetup();
  assert.match(html, /Prepare a campaign draft/);
  assert.match(html, /Exact Mailchimp audience ID/);
  assert.match(html, /Source for approved copy and offer facts/);
  assert.match(html, /Mailchimp connection: not confirmed/);
  assert.match(html, /Review campaign plan/);
  assert.match(html, /no send, schedule, live-ad or budget action/);
  assert.doesNotMatch(html, /SIMULATED|Northline|Kastner/);
});

test('saved result shows provider identity and text safely without running email HTML', () => {
  const html = renderResult({ campaignId: 'campaign-42', audienceId: 'list-42', audienceName: 'Customers',
    subject: 'Exact subject', previewText: 'Exact preview', fromName: 'Brand', replyTo: 'brand@example.test',
    body: '<script>alert("unsafe")</script>\nExact saved body\n*|UNSUB|*' });
  assert.match(html, /unsent Mailchimp draft/);
  assert.match(html, /campaign-42/);
  assert.match(html, /Customers \(list-42\)/);
  assert.match(html, /Exact saved body/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});
