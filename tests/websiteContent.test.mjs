import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { build } from 'vite';
import { primaryResultFromOutputs } from '../src/lib/resultPresentation.mjs';
import { websiteContentFiles, websiteContentZip } from '../src/lib/websiteContentExport.mjs';
import { websiteToolOutcome } from '../src/lib/websiteToolOutcomes.mjs';
import { cmsToolScreenPath, websiteCMSPreview } from '../src/lib/websiteCMSPreview.mjs';
import { unzipSync, strFromU8 } from 'fflate';

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
let temporary, render, renderTool;
before(async () => {
  const repo = fileURLToPath(new URL('../', import.meta.url));
  temporary = fs.mkdtempSync(path.join(repo, '.website-render-'));
  await build({ configFile: path.join(repo, 'vite.config.js'), logLevel: 'silent', build: {
    ssr: path.join(repo, 'tests/fixtures/websiteContentRender.jsx'), outDir: temporary, emptyOutDir: true,
    rollupOptions: { output: { entryFileNames: 'render.mjs' } } }, ssr: { noExternal: ['lucide-react'] } });
  ({ render, renderTool } = await import(pathToFileURL(path.join(temporary, 'render.mjs'))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });

test('main result is selected only from an accepted, verified website content output', () => {
  const output = { operation: 'website.content.prepare', critic: { action: 'accept' }, outcome_check: { status: 'verified' },
    provider_result: { kind: 'website_content', status: 'draft', packet } };
  assert.equal(primaryResultFromOutputs([output]).kind, 'website_content');
  assert.notEqual(primaryResultFromOutputs([{ ...output, outcome_check: { status: 'pending' } }]).kind, 'website_content');
  assert.notEqual(primaryResultFromOutputs([{ ...output, critic: { action: 'escalate' } }]).kind, 'website_content');
});

test('the complete main package leads a single set of readable simulated outcomes', () => {
  const html = render(packet);
  assert.match(html, /Main content result/);
  assert.ok(html.indexOf('Page 0 revised page') < html.indexOf('Results by tool'));
  assert.equal((html.match(/aria-label="Simulated tool outcomes"/g) || []).length, 1);
  for (const provider of ['WordPress', 'Shopify', 'WooCommerce', 'BigCommerce']) {
    assert.equal((html.match(new RegExp(`>View in ${provider}<`, 'g')) || []).length, 1);
    assert.ok(html.includes(websiteToolOutcome(provider).part));
    assert.ok(html.includes(websiteToolOutcome(provider).result));
  }
  assert.doesNotMatch(html, /Tool results|Tools used|What happened|Preview simulated CMS outputs|Hide simulated outputs|<pre|SHA-256|HTTP 200|receipt-123|Content version/);
  for (const page of packet.pages) {
    const result = render(packet, { initialPage: page.page_id });
    assert.ok(result.includes(page.sections[0].body));
    assert.ok(result.includes(page.page_title));
    assert.ok(result.includes(page.meta_description));
    assert.match(result, /Images to prepare/);
    assert.ok(!result.includes(page.version));
  }
});

test('review and developer handoff use page names and plain-language actions without changing stored evidence', () => {
  assert.match(render(packet, { initialTab: 'Changes' }), /Old title/);
  const approvals = render(packet, { initialTab: 'Approvals' });
  assert.match(approvals, /Choose a reviewer/);
  assert.match(approvals, /Review copy and images/);
  assert.doesNotMatch(approvals, /Approve &amp; publish|version-0|receipt-123/);
  assert.match(render(packet, { initialTab: 'Developer handoff' }), /create separate unpublished drafts after approval/);
  const legacy = render(packet, { initialTab: 'Tool results', initialTool: 'cms' });
  assert.match(legacy, /Main content result/);
  assert.doesNotMatch(legacy, /HTTP 200|SHA-256|receipt-123|<pre/);
  const stored = JSON.parse(websiteContentFiles(packet)['metadata.json']);
  assert.equal(stored.pages[0].content_version, packet.pages[0].version);
  assert.equal(stored.cms_drafts_created, 0);
});

test('marketing review and CMS-ready archive retain every full page, FAQ, exact version and SEO field', () => {
  const marketing = structuredClone(packet);
  for (const page of marketing.pages) {
    page.faqs = [{ question: 'Which program fits?', answer: 'Ask about your student’s current learning priorities.' }];
    page.internal_links = [{ label: 'Academic support', url: 'https://client.example/academic/', reason: 'Compare the appropriate program.' }];
    page.marketing_changes = [{ area: 'CTA', before: 'Learn more', after: 'Discuss tutoring', reason: 'Clarify the inquiry step.' }];
  }
  const files = websiteContentFiles(marketing);
  assert.equal(Object.keys(files).length, 9);
  const zip = unzipSync(websiteContentZip(marketing));
  const metadata = JSON.parse(strFromU8(zip['metadata.json']));
  assert.equal(metadata.pages.length, 5);
  assert.equal(metadata.cms_drafts_created, 0);
  for (let i = 0; i < 5; i++) {
    const record = metadata.pages[i];
    const html = strFromU8(zip[record.html_file]);
    assert.ok(html.includes(marketing.pages[i].sections[0].body));
    assert.match(html, /Questions parents ask/);
    assert.match(html, /href="https:\/\/client.example\/contact\/"/);
    assert.equal(record.content_version, marketing.pages[i].version);
    assert.equal(record.page_title, marketing.pages[i].page_title);
    assert.equal(record.meta_description, marketing.pages[i].meta_description);
    assert.equal(record.approval.status, 'pending');
  }
  assert.match(files['review.html'], /Marketing reason/);
  assert.match(render(marketing), /Parent FAQs/);
  assert.match(render(marketing, { initialTab: 'Changes' }), /Clarify the inquiry step/);
  marketing.pages[0].sections[0].body = '<script>alert("unsafe")</script>';
  assert.ok(websiteContentFiles(marketing)['pages/01-page-0.html'].includes('&lt;script&gt;'));
  marketing.pages[0].cta_target = 'javascript:alert(1)';
  assert.throws(() => websiteContentFiles(marketing), /safe HTTPS/);
});

test('CMS simulations preserve all five exact versions and never become provider receipts or approvals', () => {
  const original = structuredClone(packet);
  const preview = websiteCMSPreview(packet);
  assert.deepEqual(packet, original);
  assert.equal(preview.mode, 'simulated');
  assert.equal(preview.source_content_receipt, packet.execution.id);
  assert.equal(preview.external_calls, 0);
  assert.equal(preview.cms_records_created, 0);
  assert.equal(preview.live_pages_modified, false);
  assert.equal(preview.approvals_recorded, false);
  assert.deepEqual(preview.tools.map((tool) => tool.name), ['WordPress', 'Shopify', 'WooCommerce', 'BigCommerce']);
  for (const tool of preview.tools) {
    assert.equal(tool.mode, 'simulated');
    assert.equal(tool.connection_verified, false);
    assert.equal(tool.pages.length, 5);
    for (let i = 0; i < 5; i++) {
      const page = tool.pages[i];
      assert.equal(page.content_version, packet.pages[i].version);
      assert.equal(page.source_live_url, packet.pages[i].url);
      assert.equal(page.seo.page_title, packet.pages[i].page_title);
      assert.ok(page.body_html.includes(packet.pages[i].sections[0].body));
      assert.equal(page.remote_id, null);
      assert.equal(page.remote_url, null);
      assert.equal(page.publish_state, 'unpublished');
      assert.equal(page.approval_status, 'pending');
      assert.match(page.preview_id, /^simulated-/);
      if (tool.name === 'WooCommerce') {
        assert.equal(page.cms_owner, 'WordPress');
        assert.equal(page.products_created, 0);
      }
    }
  }
  assert.equal(websiteContentFiles(packet)['metadata.json'].includes('"cms_drafts_created": 0'), true);
});

test('only simulated CMS outcomes are offered, with readable fallbacks when no tool route exists', () => {
  const html = render(packet);
  assert.equal(html, render(packet, { initialSimulation: true }));
  assert.match(html, /Simulated previews only/);
  assert.match(html, /alternative destinations for this task/);
  for (const tool of websiteCMSPreview(packet).tools) {
    assert.ok(html.includes(`href="/runs/test-run/tools/${tool.name.toLowerCase()}"`));
    const fallback = render(packet, { runId: null, initialTool: tool.id });
    assert.ok(fallback.includes(`${tool.name} simulated outcome`));
    assert.ok(fallback.includes(packet.pages[0].sections[0].body));
    assert.doesNotMatch(fallback, /<pre|Complete HTML body|Structured .* output|body_html|remote_id|schema_version/);
  }
});

test('view-in-tool links open isolated named tool screens rather than an AURA output tab', () => {
  assert.equal(cmsToolScreenPath('test-run', 'wordpress-preview'), '/runs/test-run/tools/wordpress');
  assert.equal(cmsToolScreenPath('../other-run', 'wordpress-preview'), null);
  assert.equal(cmsToolScreenPath('test-run', 'external-provider-preview'), null);
  assert.equal(cmsToolScreenPath(null, 'shopify-preview'), null);
  const html = render(packet, { initialSimulation: true });
  assert.doesNotMatch(html, /View in AURA/);
  for (const tool of websiteCMSPreview(packet).tools) {
    const list = renderTool(tool);
    assert.ok(list.includes(`${tool.name} simulated tool screen`));
    assert.ok(list.includes(`Simulated ${tool.name} screen`));
    assert.match(list, /Back to AURA results/);
    assert.match(list, /Search draft pages/);
    assert.ok(list.includes(websiteToolOutcome(tool.name).part));
    for (const page of packet.pages) assert.ok(!list.includes(page.version));
    const editor = renderTool(tool, { initialPageId: packet.pages[0].page_id });
    assert.match(editor, /Page editor sections/);
    assert.match(editor, /Preview page/);
    assert.ok(editor.includes(packet.pages[0].sections[0].body));
    assert.ok(!editor.includes(packet.pages[0].version));
    assert.match(editor, /Part of your task/);
    assert.match(editor, /Search listing/);
    assert.match(editor, /Copy and images await approval/);
    assert.doesNotMatch(editor, /type="password"|name="client_secret"|>Publish<|CMS records created successfully/);
  }
});
