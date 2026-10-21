import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { build } from 'vite';
import { primaryResultFromOutputs } from '../src/lib/resultPresentation.mjs';
import { websiteContentFiles, websiteContentZip } from '../src/lib/websiteContentExport.mjs';
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
  assert.ok(content.indexOf('Select tool result') < content.indexOf('Revised copy · unpublished review draft'));
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

test('screenshot-style per-tool rows expose full simulated outputs with honest status', () => {
  const real = render(packet);
  assert.match(real, /What happened/);
  assert.match(real, /Tools used/);
  assert.doesNotMatch(real, /View in Shopify/);
  const simulated = render(packet, { initialSimulation: true });
  for (const provider of ['WordPress', 'Shopify', 'WooCommerce', 'BigCommerce']) {
    assert.ok(simulated.includes(`View in ${provider}`));
    assert.ok(simulated.includes(`href="/runs/test-run/tools/${provider.toLowerCase()}"`));
  }
  assert.match(simulated, /Simulation mode/);
  assert.match(simulated, /No CMS API calls, records, approvals or live changes were made/);
  for (const tool of websiteCMSPreview(packet).tools) {
    const html = render(packet, { initialSimulation: true, initialTab: 'Tool results', initialTool: tool.id });
    assert.ok(html.includes(`${tool.name} simulated output`));
    assert.match(html, /Simulated tool output/);
    assert.match(html, /0 CMS records created/);
    for (const page of packet.pages) {
      assert.ok(html.includes(page.version));
      assert.ok(html.includes(page.sections[0].body));
    }
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
    for (const page of packet.pages) assert.ok(list.includes(page.content_version || page.version));
    const editor = renderTool(tool, { initialPageId: packet.pages[0].page_id });
    assert.match(editor, /Page editor sections/);
    assert.match(editor, /Preview page/);
    assert.ok(editor.includes(packet.pages[0].sections[0].body));
    assert.ok(editor.includes(packet.pages[0].version));
    assert.match(editor, /Content approval pending/);
    assert.doesNotMatch(editor, /type="password"|name="client_secret"|>Publish<|CMS records created successfully/);
  }
});
