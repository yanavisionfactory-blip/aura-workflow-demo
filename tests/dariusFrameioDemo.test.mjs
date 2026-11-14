import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { launchRequest, normalizeAssetUrl } from '../public/showcase/darius-bright/launch.mjs';
import { originalPrompt, findings, originalReport } from '../public/showcase/darius-bright/data.mjs';

const url = 'https://app.frame.io/project/11111111-1111-4111-8111-111111111111/view/22222222-2222-4222-8222-222222222222';
test('external launcher uses only the supplied asset and never claims an automatic live run', () => {
  const launch = launchRequest(url, originalPrompt);
  assert.ok(launch.includes(url));
  assert.ok(launch.includes(originalPrompt));
  assert.ok(launch.includes('aura_frameio_prepare_review_from_link'));
  assert.ok(launch.includes('frameio.assistant.browser_review'));
  assert.ok(launch.includes('Never substitute AURA Intelligence'));
  assert.ok(launchRequest('', originalPrompt).includes('[Paste my exact Frame.io asset URL'));
  assert.equal(normalizeAssetUrl(url + '?token=secret#comment'), url);
  for (const invalid of [url.replace('app.frame.io', 'evil.test'), url.replace('app.frame.io', 'user@app.frame.io'), url.replace('/view/', '/review/'), 'https://f.io/shared']) {
    assert.equal(normalizeAssetUrl(invalid), null);
  }
});
test('public snapshot faithfully preserves native findings and limitations', () => {
  assert.equal(originalReport, readFileSync(new URL('../public/showcase/darius-bright/frameio-review.md', import.meta.url), 'utf8'));
  assert.equal(findings.length, 16);
  assert.equal(findings.filter(row => row.status === 'Observed').length, 12);
  assert.ok(originalReport.includes('Audio: the native analysis could not access the soundtrack'));
  for (const row of findings) { assert.ok(originalReport.includes(row.finding)); assert.ok(originalReport.includes(row.correction)); }
  const html = readFileSync(new URL('../public/showcase/darius-bright/index.html', import.meta.url), 'utf8');
  assert.ok(html.includes("connect-src 'none'"));
  assert.ok(html.includes('noindex,nofollow'));
});
