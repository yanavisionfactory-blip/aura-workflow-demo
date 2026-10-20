import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'vite';
import packet from '../src/showcase/weekly-account-review/data.mjs';
import { tour } from '../src/showcase/weekly-account-review/scenario.mjs';

const repo = fileURLToPath(new URL('../', import.meta.url));
let temporary, render, renderCreative;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, '.weekly-render-'));
  await build({ configFile: path.join(repo, 'vite.weekly.config.js'), logLevel: 'silent', build: { ssr: path.join(repo, 'tests/fixtures/weeklyReviewRender.jsx'), outDir: temporary, emptyOutDir: true, rollupOptions: { output: { entryFileNames: 'render.mjs' } } }, ssr: { noExternal: ['lucide-react'] } });
  ({ render, renderCreative } = await import(pathToFileURL(path.join(temporary, 'render.mjs'))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });

test('weekly workflow renders the original brief, scope review and honest native playback', () => {
  const input = render('input');
  assert.match(input, /Prepare a weekly account review for one SmartSites client/);
  assert.match(input, /Do not launch campaigns, change budgets or send messages/);
  assert.match(input, /Create plan/);
  assert.match(render('plan'), /Review before running/);
  const review = render('review');
  assert.match(review, /Source and scope preview/);
  assert.match(review, /Reporting periods and definitions/);
  assert.match(review, /Approve &amp; run demo/);
  for (const name of packet.scope.excluded) assert.ok(review.includes(name));
  assert.match(review, /this client’s setup is unconfirmed/);
  const execution = render('execution');
  assert.match(execution, /Playing the prepared workflow/);
  assert.match(execution, /all account metrics are simulated/);
  assert.doesNotMatch(execution, /notify you when/);
});

test('weekly result has one checked summary and exposes all three scoped platform outputs', () => {
  const overview = render('results');
  for (const label of ['What happened', 'Tools used in this scenario', 'Checked summary', 'Material changes to review', 'Separate platform attribution', 'All account metrics are simulated']) assert.ok(overview.includes(label));
  assert.match(overview, /5,130/);
  assert.match(overview, /10800|10,800/);
  assert.match(overview, /No blended ROAS|no combined revenue total/);
  for (const source of packet.sources) {
    const output = render('results', { tab: 'Tool activity', source: source.key });
    assert.ok(output.includes(`${source.name} sample output`));
    assert.ok(output.includes(source.rows[0].id));
    assert.match(output, /Download sample CSV/);
    assert.match(output, /No live provider report exists/);
  }
});

test('three experiment proposals and all six creative variants render with their evidence and limits', () => {
  for (const item of packet.experiments) {
    const html = render('results', { tab: 'Experiments', experiment: item.id });
    assert.ok(html.includes(`${item.id} experiment proposal`));
    for (const field of ['Supporting evidence', 'Hypothesis', 'Primary metric', 'Guardrails', 'Decision rule', 'Power and feasibility review', 'Dependencies']) assert.ok(html.includes(field));
  }
  for (const creative of packet.creatives) for (let index = 0; index < 2; index++) {
    const html = renderCreative(creative.id, index);
    assert.match(html, /Draft preview in AURA/);
    assert.ok(html.includes(creative.variants[index].subject || creative.variants[index].hook || creative.variants[index].headlines[0]));
    assert.match(html, /Copy draft text/);
    assert.doesNotMatch(html, /type="submit"|href="https:\/\/northline-home.example/);
  }
});

test('backlog and intake keep evidence, ownership, brand assumptions and reporting destination gaps visible', () => {
  const backlog = render('results', { tab: 'Backlog', priority: 'P1', task: 'B02' });
  for (const field of ['Evidence', 'Proposed fix', 'Effort', 'Priority reasoning', 'Acceptance check', 'Dependencies', 'Affected campaigns / segments']) assert.ok(backlog.includes(field));
  const intake = render('results', { tab: 'Sources & scope' });
  assert.match(intake, /Scenario goals and brand brief/);
  assert.match(intake, /Period and metric dictionary/);
  assert.match(intake, /SmartSites Client Hub/);
  assert.match(intake, /selected account unconfirmed/);
  for (const name of packet.scope.excluded) assert.ok(intake.includes(name));
  assert.match(intake, /Contradictions and checks requiring expert review/);
  assert.doesNotMatch(intake, /client-dashboard.example|href="\/runs\//);
});

test('every guided result step renders and the public entry prohibits backend calls', () => {
  for (const item of tour.filter((step) => step.phase === 'results')) {
    const html = render('results', item.focus || null);
    assert.match(html, /Weekly account review prepared/);
    if (item.focus?.tab) assert.ok(html.includes(`aria-labelledby="weekly-tab-${item.focus.tab.replaceAll(' ', '-').replaceAll('&', '&amp;')}"`));
  }
  const guide = render('input', null, true);
  assert.match(guide, /Guided walkthrough/);
  assert.match(guide, /Pause/);
  assert.match(guide, /Next/);
  const entry = fs.readFileSync(path.join(repo, 'showcase/weekly-account-review/index.html'), 'utf8');
  assert.match(entry, /connect-src 'none'/);
  assert.match(entry, /Weekly account review interactive demo/);
  assert.match(render('feedback'), /No email or form submission is made/);
});
