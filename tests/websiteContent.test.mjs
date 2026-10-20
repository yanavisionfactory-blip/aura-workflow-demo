import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { build } from 'vite';
import { primaryResultFromOutputs } from '../src/lib/resultPresentation.mjs';

const packet = {
  client: 'Example Learning', summary: 'Five complete drafts.', working_brief: 'Supportive voice.', brief_status: 'Client approval pending',
  pages: Array.from({ length: 5 }, (_, index) => ({ page_id: `P${index + 1}`, version: `version-${index}`,
    url: `https://client.example/page-${index}/`, h1: `Revised heading ${index}`, purpose: 'Explain the service.',
    sections: [{ heading: 'Personal learning', body: `Complete revised page body ${index}.` }],
    cta_label: 'Discuss tutoring', cta_target: 'https://client.example/contact/', page_title: 'Revised title',
    meta_description: 'A revised description.', assets: [{ requirement: 'Tutoring photo', alt_text: 'Tutor', crop: 'Landscape',
      candidate_url: '', approval_status: 'pending', rights_status: 'unverified' }],
    review_notes: ['Confirm rights.'], original: { excerpt: 'Current source excerpt.', title: 'Old title', description: 'Old description',
      headings: [{ level: 1, text: 'Old heading' }] }, change_reason: 'Clarifies the service.', source_id: `P${index + 1}`,
    sitemap_member: true, approval: { status: 'pending', reviewer: null, evidence: null } })),
  sources: [{ source: { key: 'cms', role: 'cms', title: 'Example Learning', url: 'https://client.example/wp-json/', cms: 'WordPress' },
    receipt: { status: 200, fetched_at: '2026-10-20T20:00:00Z', bytes: 1200, sha256: 'a'.repeat(64) } }],
  systems: [{ area: 'CMS', tool: 'WordPress', status: 'Public site evidence', detail: 'Authenticated account unverified.' }],
  discovery: {}, staging: { reason: 'Await exact content approval.' }, handoff: ['Create separate unpublished page records.'],
  execution: { mode: 'live_public_sources', model: 'test-model', model_attempts: 1, id: 'receipt-123', executed_at: '2026-10-20T20:00:00Z' },
};
let temporary, render;
before(async () => {
  const repo = fileURLToPath(new URL('../', import.meta.url));
  temporary = fs.mkdtempSync(path.join(repo, '.website-render-'));
  await build({ configFile: path.join(repo, 'vite.config.js'), logLevel: 'silent', build: {
    ssr: path.join(repo, 'tests/fixtures/websiteContentRender.jsx'), outDir: temporary, emptyOutDir: true,
    rollupOptions: { output: { entryFileNames: 'render.mjs' } } }, ssr: { noExternal: ['lucide-react'] } });
  ({ render } = await import(pathToFileURL(path.join(temporary, 'render.mjs'))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });

test('main result is selected only from an accepted, verified website content output', () => {
  const output = { operation: 'website.content.prepare', critic: { action: 'accept' }, outcome_check: { status: 'verified' },
    provider_result: { kind: 'website_content', status: 'draft', packet } };
  assert.equal(primaryResultFromOutputs([output]).kind, 'website_content');
  assert.notEqual(primaryResultFromOutputs([{ ...output, outcome_check: { status: 'pending' } }]).kind, 'website_content');
  assert.notEqual(primaryResultFromOutputs([{ ...output, critic: { action: 'escalate' } }]).kind, 'website_content');
});

test('all five full page drafts and per-tool output entry points are rendered', () => {
  const html = render(packet);
  assert.match(html, /Results — the actual output/);
  assert.match(html, /View AURA content package result/);
  assert.match(html, /View WordPress result/);
  assert.match(html, /View Existing website &amp; sitemap result/);
  for (const page of packet.pages) {
    const result = render(packet, { initialPage: page.page_id });
    assert.ok(result.includes(page.sections[0].body));
    assert.ok(result.includes(page.page_title));
    assert.ok(result.includes(page.meta_description));
    assert.match(result, /Asset requirements/);
  }
});

test('changes, pending approvals, structured handoff and actual receipts are independently inspectable', () => {
  assert.match(render(packet, { initialTab: 'Changes' }), /Old title/);
  const approvals = render(packet, { initialTab: 'Approvals' });
  assert.match(approvals, /Unassigned/);
  assert.match(approvals, /Not created/);
  assert.doesNotMatch(approvals, /Approve &amp; publish/);
  assert.match(render(packet, { initialTab: 'Developer handoff' }), /Create separate unpublished/);
  const cms = render(packet, { initialTab: 'Tool results', initialTool: 'cms' });
  assert.match(cms, /HTTP 200/);
  assert.match(cms, /SHA-256/);
  assert.match(cms, /not authenticated draft access/);
  const content = render(packet, { initialTab: 'Tool results', initialTool: 'content' });
  assert.match(content, /receipt-123/);
  assert.match(content, /Complete revised page body 0/);
});
