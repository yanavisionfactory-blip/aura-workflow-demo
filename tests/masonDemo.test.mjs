import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {JSDOM} from 'jsdom';
import {mountDemo} from '../public/showcase/mason-green/app.mjs';
import {rows,retryPrompt,originalSheet} from '../public/showcase/mason-green/data.mjs';
import {workflowInputPrompt} from '../src/lib/runtimePlan.mjs';

const html=fs.readFileSync(new URL('../public/showcase/mason-green/index.html',import.meta.url),'utf8');
function page(){const dom=new JSDOM(html,{url:'https://yanavisionfactory-blip.github.io/aura-workflow-demo/showcase/mason-green/'});mountDemo(dom.window.document);return dom;}

test('Mason demo leads with the saved output and preserves the exact read-back across views',()=>{
  const dom=page(),d=dom.window.document;
  assert.equal(rows.length,37);assert.ok(rows.every(row=>row.length===6));
  assert.equal(d.querySelector('main > section[id]').id,'result');
  assert.equal(d.querySelector('#result-table tbody').rows.length,4);
  assert.match(d.querySelector('#result-table').textContent,/Not publicly reported/);
  assert.match(d.querySelector('#result-table').textContent,/2.6%/);
  assert.equal(d.querySelector('#original-sheet').href,originalSheet);
  assert.ok([...d.querySelectorAll('details')].every(el=>!el.open));
  d.querySelector('[data-view="comparison"]').click();
  assert.match(d.querySelector('#result-table').textContent,/\$70/);
  assert.match(d.querySelector('#result-table').textContent,/\$41.99/);
  assert.equal(d.querySelector('#sheet-panel').getAttribute('aria-labelledby'),'tab-comparison');
  d.querySelector('[data-view="comparison"]').dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'End',bubbles:true}));
  assert.equal(d.querySelector('[data-view="all"]').getAttribute('aria-selected'),'true');
  const actual=[...d.querySelectorAll('#result-table tbody tr')].map(row=>[...row.cells].slice(1).map(cell=>cell.textContent));
  assert.deepEqual(actual,rows);
  dom.window.close();
});

test('trying the demo opens a fresh AURA prompt and never carries a saved run or account',()=>{
  const dom=page(),d=dom.window.document,input=d.querySelector('#retry-prompt'),link=d.querySelector('#try-aura');
  let url=new URL(link.href);
  assert.equal(url.pathname,'/aura-workflow-demo/');
  assert.deepEqual([...url.searchParams.keys()],['prompt']);
  assert.equal(workflowInputPrompt({search:url.search}),retryPrompt);
  input.value='Create my own KPI sheet & keep missing values blank.';
  input.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
  url=new URL(link.href);assert.equal(workflowInputPrompt({search:url.search}),input.value);
  input.value=' ';input.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
  assert.equal(link.hasAttribute('href'),false);assert.equal(link.getAttribute('aria-disabled'),'true');
  d.querySelector('#restore-prompt').click();assert.equal(input.value,retryPrompt);assert.ok(link.hasAttribute('href'));
  dom.window.close();
});

test('the demo is explicit about unfinished work, and feedback is copied without being sent',async()=>{
  const dom=page(),d=dom.window.document,copied=[];
  Object.defineProperty(dom.window.navigator,'clipboard',{value:{writeText:async text=>copied.push(text)}});
  assert.match(d.querySelector('#verification-output').textContent,/fixes and correction prompts/);
  assert.match(d.querySelector('#verification-output').textContent,/entire workbook was not independently checked/);
  assert.match(d.querySelector('#research-output').textContent,/one blocked source/);
  assert.match(d.querySelector('#report-output').textContent,/generated through ChatGPT/);
  assert.match(d.querySelector('meta[http-equiv="Content-Security-Policy"]').content,/connect-src 'none'/);
  assert.doesNotMatch(html,/greenmason955|yanak2465|yana\.visionfactory|3bac88bf|29960|35000/);
  d.querySelector('#copy-feedback').click();assert.equal(copied.length,0);
  d.querySelector('#feedback').value='The sheet saved in my account; the sources were clear.';
  d.querySelector('#copy-feedback').click();await Promise.resolve();
  assert.equal(copied.length,1);assert.match(copied[0],/The sheet saved in my account/);
  d.querySelector('#copy-prompt').click();await Promise.resolve();assert.equal(copied[1],retryPrompt);
  dom.window.close();
});
