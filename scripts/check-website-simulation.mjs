// UI regression test against an isolated local build, never a user browser/session.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { chromium } from 'playwright';
import { unzipSync, strFromU8 } from 'fflate';

const root = path.resolve('dist'), proof = path.resolve('.website-simulation-proof');
await fs.mkdir(proof, { recursive: true });
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };
const server = http.createServer(async (req, res) => {
  try {
    let pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (pathname.endsWith('/')) pathname += 'index.html';
    const file = path.resolve(root, `.${pathname}`);
    if (!file.startsWith(`${root}${path.sep}`)) { res.writeHead(403).end(); return; }
    const data = await fs.readFile(file); res.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream' }); res.end(data);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', acceptDownloads: true });
  const external = [], errors = [];
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin === origin) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${origin}/showcase/website-content/?screen=simulate`);
  await page.getByRole('button', { name: 'Start website workflow with simulated data', exact: true }).click();
  await page.getByRole('heading', { name: 'Review your sample content package', exact: true }).waitFor();
  const stage = page.getByRole('button', { name: 'Create and verify drafts in all four simulated CMS tools', exact: true });
  assert.equal(await stage.isEnabled(), false);
  assert.equal(await page.locator('[aria-label="Simulated tool outcomes"]').count(), 0);
  await page.getByRole('tab', { name: 'Changes', exact: true }).click();
  await page.getByRole('heading', { name: 'What changed on Home', exact: true }).waitFor();
  await page.getByRole('tab', { name: 'Approvals', exact: true }).click();
  assert.match(await page.locator('[role="tabpanel"]').innerText(), /Pending/);
  await page.getByRole('checkbox', { name: 'I approve the sample copy and image manifest for this simulation only.', exact: true }).check();
  await stage.click();
  await page.getByRole('heading', { name: 'Website workflow completed · 12 of 12 steps', exact: true }).waitFor();
  const resultUrl = page.url();
  assert.equal(await page.locator('[aria-label="Simulated tool outcomes"]').count(), 1);
  assert.equal(await page.locator('pre').count(), 0);
  await page.getByRole('tab', { name: 'Pages', exact: true }).click();
  await page.screenshot({ path: path.join(proof, 'completed-result.jpg'), type: 'jpeg', quality: 90 });
  for (const name of ['WordPress', 'Shopify', 'WooCommerce', 'BigCommerce']) {
    await page.getByRole('link', { name: `View in ${name}`, exact: true }).click();
    await page.getByText('5 simulated drafts created · 5 readbacks passed', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: /^Open .+ draft$/ }).count(), 5);
    await page.getByRole('button', { name: 'Open Home draft', exact: true }).click();
    await page.getByRole('tab', { name: 'Search listing', exact: true }).click();
    assert.match(await page.getByRole('tabpanel').innerText(), /Kastner Hill Learning/);
    await page.getByRole('tab', { name: 'Images', exact: true }).click();
    assert.match(await page.getByRole('tabpanel').innerText(), /real rights unconfirmed/);
    await page.getByRole('tab', { name: 'Content', exact: true }).click();
    if (name === 'Shopify') await page.screenshot({ path: path.join(proof, 'shopify-verified-draft.jpg'), type: 'jpeg', quality: 90 });
    await page.getByRole('link', { name: 'Back to AURA results', exact: true }).click();
  }
  await page.goto(resultUrl);
  await page.getByRole('heading', { name: 'Website workflow completed · 12 of 12 steps', exact: true }).waitFor();
  await page.getByRole('tab', { name: 'Developer handoff', exact: true }).click();
  const pendingDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download website files for your developer', exact: true }).click();
  const download = await pendingDownload;
  const zipPath = path.join(proof, 'aura-website-simulation.zip'); await download.saveAs(zipPath);
  const files = unzipSync(await fs.readFile(zipPath));
  const run = JSON.parse(strFromU8(files['simulation-evidence.json']));
  assert.equal(run.completed_steps, 12); assert.equal(run.simulated_records_created, 20); assert.equal(run.verified_readbacks, 20);
  assert.equal(run.tools.reduce((count, tool) => count + tool.operations.length, 0), 40);
  assert.equal(external.length, 0, `Unexpected non-local requests: ${JSON.stringify(external)}`);
  assert.equal(errors.length, 0, `Browser errors: ${JSON.stringify(errors)}`);
  await fs.writeFile(path.join(proof, 'checks.json'), JSON.stringify({ passed: true, completed_steps: 12, simulated_drafts: 20, verified_readbacks: 20, cms_operations: 40, actual_provider_requests: external.length, page_errors: errors, reload_restored: true, developer_zip_checked: true, simulation_id: run.id }, null, 2));
  console.log('PASS: 12 steps, 4 CMS adapters, 20 drafts, 20 readbacks, approval gate, reload, developer ZIP, zero external calls.');
  await context.close();
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
