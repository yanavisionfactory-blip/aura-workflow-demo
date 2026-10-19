import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { build } from 'vite';
import data from '../src/showcase/seo-audit/data.mjs';
import { originalPrompt } from '../src/showcase/seo-audit/scenario.mjs';

const repo = fileURLToPath(new URL('../', import.meta.url));
let temporary;
let render;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, '.seo-render-'));
  await build({
    configFile: path.join(repo, 'vite.showcase.config.js'),
    logLevel: 'silent',
    build: { ssr: path.join(repo, 'tests/fixtures/seoShowcaseRender.jsx'), outDir: temporary, emptyOutDir: true, rollupOptions: { output: { entryFileNames: 'render.mjs' } } },
    ssr: { noExternal: ['lucide-react'] },
  });
  ({ render } = await import(pathToFileURL(path.join(temporary, 'render.mjs'))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });

test('anonymized snapshot retains observed counts, URL evidence and duplicate-export limits', () => {
  assert.equal(data.crawl.counts.url_records, 171);
  assert.equal(data.crawl.counts.canonical_conflicts, 82);
  assert.equal(data.crawl.counts.indexable_html, 4);
  assert.equal(data.crawl.counts.link_edge_rows, 0);
  assert.equal(data.backlog.length, 10);
  assert.equal(data.crawl.files[1].duplicate_of, data.crawl.files[0].filename);
  assert.equal(data.crawl.issues.find((issue) => issue.id === 'T01').affected.length, 82);
  const serialized = JSON.stringify(data);
  assert.doesNotMatch(serialized, /data:text\/csv|oauth_access_token|api_key|workspace_id|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}/i);
  for (const row of data.crawl.issues.flatMap((issue) => issue.affected)) {
    if (row.url) assert.equal(new URL(row.url).hostname, 'client.example');
    assert.ok(row.csv_row);
  }
});

test('native workflow phases render the original task, review gate and honest playback', () => {
  assert.match(render('input'), /What would you like/);
  assert.match(render('input'), /Create plan/);
  const confirmation = render('input', null, true);
  assert.match(confirmation, /Semrush: keyword, competitor, ranking and backlink research/);
  assert.match(confirmation, /Do not modify the website/);
  assert.equal(originalPrompt.includes('Reporting and task-management destinations: confirm their names.'), true);
  const plan = render('plan');
  for (const tool of ['Screaming Frog', 'Semrush', 'Ahrefs', 'Sitebulb']) assert.ok(plan.includes(tool));
  assert.doesNotMatch(plan, /Drag to reorder|Change the tool/);
  const review = render('review');
  assert.match(review, /Review before running/);
  assert.match(review, /Source preview/);
  assert.match(review, /Result preview/);
  assert.match(review, /What will happen/);
  assert.match(review, /Approve &amp; run demo/);
  assert.match(review, /engagement with Mantas Auk unconfirmed/);
  assert.doesNotMatch(review, /0 changes need approval/);
  const execution = render('execution');
  assert.match(execution, /Playing the prepared workflow/);
  assert.match(execution, /No live connections or external writes/);
  assert.doesNotMatch(execution, /notify you when/);
});

test('native results expose every tool output and a URL-level implementation backlog', () => {
  const result = render('results');
  assert.match(result, /What happened/);
  assert.match(result, /Tools used/);
  assert.match(result, /171 Screaming Frog URL records imported/);
  assert.match(result, /Implementation roadmap/);
  for (const [tool, title] of [['semrush', 'Keyword positions'], ['ahrefs', 'Backlink sample'], ['sitebulb', 'Technical audit hints']]) {
    const html = render('results', { tab: 'Tool activity', tool });
    assert.ok(html.includes(title), `${tool} output should render ${title}`);
    assert.match(html, /simulated output/i);
    assert.match(html, /No provider request was made/);
  }
  const crawl = render('results', { tab: 'Tool activity', tool: 'crawl' });
  assert.match(crawl, /Export analysed/);
  assert.match(crawl, /82 URLs/);
  const backlog = render('results', { tab: 'Backlog', priority: 'P1', issue: 'T01' });
  for (const label of ['Evidence', 'Proposed fix', 'Effort', 'Dependencies', 'Priority reasoning', 'Expert review', 'Acceptance check', 'Affected URL']) assert.ok(backlog.includes(label));
  assert.match(backlog, /CSV row/);
  const intake = render('results', { tab: 'Sources & intake' });
  assert.match(intake, /Contradictions and checks/);
  assert.match(intake, /Not independent crawl evidence/);
  assert.match(intake, /Google Docs and Jira/);
  assert.doesNotMatch(result + backlog + intake, /href="\/runs\//);
});

test('feedback stays local and the static entry prohibits backend requests', () => {
  const html = render('feedback');
  assert.match(html, /Copy feedback/);
  assert.match(html, /No email or form submission is made/);
  assert.match(html, /give separate permission/);
  assert.doesNotMatch(html, /<form|type="submit"/);
  const entry = fs.readFileSync(path.join(repo, 'showcase/seo-audit/index.html'), 'utf8');
  assert.match(entry, /connect-src 'none'/);
  assert.match(entry, /src="\.\.\/\.\.\/src\/showcase\/seo-audit\/main.jsx"/);
  assert.equal(fs.existsSync(path.join(repo, 'public/showcase/seo-audit/walkthrough.mp4')), false);
});
