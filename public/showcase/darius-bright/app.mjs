import { originalPrompt, findings, originalReport } from './data.mjs';
import { launchRequest, normalizeAssetUrl } from './launch.mjs';

const $ = selector => document.querySelector(selector);
const prompt = $('#review-prompt'), asset = $('#asset-url'), video = $('#sample-video');
prompt.value = originalPrompt;
$('#original-report').textContent = originalReport;

function render(filter = 'All') {
  const rows = findings.filter(row => filter === 'All' || row.status === filter);
  $('#finding-count').textContent = `${rows.length} entries`;
  $('#findings').replaceChildren(...rows.map(row => {
    const article = document.createElement('article'); article.className = 'finding';
    const heading = document.createElement('div'); heading.className = 'finding-heading';
    const timestamp = document.createElement(row.seconds === null ? 'span' : 'button');
    timestamp.className = 'timestamp'; timestamp.textContent = row.timestamp;
    if (row.seconds !== null) timestamp.addEventListener('click', () => {
      video.currentTime = row.seconds; video.pause();
      $('#seek-status').textContent = `Paused at ${row.seconds.toFixed(2)}s · ${row.timestamp}`;
      if (matchMedia('(max-width: 760px)').matches) video.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    const status = document.createElement('span'); status.className = `finding-status ${row.status.toLowerCase()}`; status.textContent = row.status;
    heading.append(timestamp, status);
    const issue = document.createElement('p'); issue.textContent = row.finding;
    const fix = document.createElement('div'); fix.className = 'correction';
    const label = document.createElement('strong'); label.textContent = 'Correction';
    const text = document.createElement('p'); text.textContent = row.correction;
    fix.append(label, text); article.append(heading, issue, fix); return article;
  }));
  $('#findings').scrollTop = 0;
}
render();
document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('[data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  render(button.dataset.filter);
}));

function updateLaunch() {
  $('#launch-request').value = launchRequest(asset.value, prompt.value);
  asset.removeAttribute('aria-invalid');
}
asset.addEventListener('input', updateLaunch); prompt.addEventListener('input', updateLaunch);
$('#restore-prompt').addEventListener('click', () => { prompt.value = originalPrompt; updateLaunch(); });
updateLaunch();

async function copy(text, message) {
  try { await navigator.clipboard.writeText(text); $('#launch-status').textContent = message; }
  catch {
    $('.launch-preview').open = true;
    $('#launch-request').value = text; $('#launch-request').focus(); $('#launch-request').select();
    $('#launch-status').textContent = 'Select and copy the text below. Automatic clipboard access is unavailable in this browser.';
  }
}
$('#copy-prompt').addEventListener('click', () => copy(prompt.value, 'Prompt copied. This does not start a run.'));
$('#copy-launch').addEventListener('click', () => {
  if (!normalizeAssetUrl(asset.value)) {
    asset.setAttribute('aria-invalid', 'true'); asset.focus();
    $('#launch-status').textContent = 'Add your exact Frame.io asset URL first: https://app.frame.io/project/PROJECT_UUID/view/FILE_UUID'; return;
  }
  if (prompt.value.trim().length < 20 || prompt.value.length > 6000) {
    prompt.focus(); $('#launch-status').textContent = 'Use a review prompt between 20 and 6,000 characters.'; return;
  }
  updateLaunch();
  copy($('#launch-request').value, 'Launch request copied. Paste it into ChatGPT with browser access to start a new AURA workflow.');
});
$('#show-screen').addEventListener('click', () => $('#screen-dialog').showModal());
$('#close-screen').addEventListener('click', () => $('#screen-dialog').close());
$('#screen-dialog').addEventListener('click', event => { if (event.target === $('#screen-dialog')) $('#screen-dialog').close(); });
