import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {campaigns,totals,money,views,retryPrompt,originalSheet} from '../public/showcase/elias-blake/data.mjs';
import {auraUrl} from '../public/showcase/elias-blake/app.mjs';

test('corrected Reddit snapshot includes the screenshot campaign and the second campaign',()=>{
  const pilot=campaigns.find(c=>c.name==='AURA pilot');
  assert.equal(pilot.impressions,16054);assert.equal(pilot.clicks,69);assert.equal(money(pilot.spend),'€32.92');
  const total=totals('Reddit Ads');
  assert.equal(total.impressions,18490);assert.equal(total.clicks,79);assert.equal(money(total.spend),'€64.67');
  assert.equal(money(totals('Google Ads').spend),'€173.23');
  assert.equal(views.campaigns.rows.length,3);
  assert.match(views.coverage.rows.flat().join(' '),/leads were not requested/);
});

test('try link carries only the editable prompt into AURA, without a saved account or run',()=>{
  const url=new URL(auraUrl(retryPrompt,'https://yanavisionfactory-blip.github.io/aura-workflow-demo/showcase/elias-blake/'));
  assert.equal(url.pathname,'/aura-workflow-demo/');
  assert.deepEqual([...url.searchParams.keys()],['prompt']);
  assert.equal(url.searchParams.get('prompt'),retryPrompt);
  assert.match(originalSheet,/\/1M19njKrX9F3rEdzZL1BIM0kdi4Omf_tU-0njsBLxhtA\/edit$/);
});

test('standalone demo prohibits live connections and labels saved-data limitations',()=>{
  const html=fs.readFileSync(new URL('../public/showcase/elias-blake/index.html',import.meta.url),'utf8');
  const app=fs.readFileSync(new URL('../public/showcase/elias-blake/app.mjs',import.meta.url),'utf8');
  assert.match(html,/connect-src 'none'/);
  assert.match(html,/different periods/);
  assert.match(html,/completed with assistance/);
  assert.doesNotMatch(html+app,/fetch\(|XMLHttpRequest|localStorage|sessionStorage|@gmail\.com|Bearer /);
  for(const name of ['style.css','data.mjs','app.mjs','saved-campaigns.csv','aura-saved-result.jpg','campaign-report.pptx',...Array.from({length:4},(_,i)=>`slide-${i+1}.png`)]){
    assert.ok(fs.statSync(new URL('../public/showcase/elias-blake/'+name,import.meta.url)).size>0,name);
  }
});
