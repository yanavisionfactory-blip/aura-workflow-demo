import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {build} from 'vite';
import {brief,packets,tools,toolState,downloadPacket} from '../src/showcase/marketing-workflow/data.mjs';
import {tour,sceneFromSearch} from '../src/showcase/marketing-workflow/scenario.mjs';

const repo=fileURLToPath(new URL('../',import.meta.url));
let temporary,render;
before(async()=>{
  temporary=fs.mkdtempSync(path.join(repo,'.marketing-showcase-render-'));
  await build({configFile:path.join(repo,'vite.marketing.config.js'),logLevel:'silent',
    build:{ssr:path.join(repo,'tests/fixtures/marketingShowcaseRender.jsx'),outDir:temporary,emptyOutDir:true,rollupOptions:{output:{entryFileNames:'render.mjs'}}},
    ssr:{noExternal:['lucide-react']}});
  ({render}=await import(pathToFileURL(path.join(temporary,'render.mjs'))));
});
after(()=>{if(temporary)fs.rmSync(temporary,{recursive:true,force:true});});

test('public marketing demo opens with the actual creative, before six collapsed supporting dropdowns',()=>{
  const html=render();
  const main=html.indexOf('aria-label="Main campaign outcome"');
  const supporting=html.indexOf('aria-label="Supporting outputs"');
  assert.ok(main>0&&main<supporting);
  assert.ok(html.slice(main,supporting).includes('Facebook Feed'));
  assert.ok(html.slice(main,supporting).includes('Your First House Blend: 10% Off'));
  assert.ok(html.slice(main,supporting).includes('Primary text'));
  assert.equal((html.match(/<details\b/g)||[]).length,6);
  assert.doesNotMatch(html,/<details[^>]*\bopen(?:=|[ >])/);
  for(const id of ['google','mailchimp','klaviyo','coordination','measurement','approvals'])assert.ok(html.includes(`id="demo-${id}"`));
  assert.doesNotMatch(html,/Google Ads interface preview|Mailchimp interface preview|Klaviyo interface preview/);
  assert.match(html,/Prepared public demo · all data is synthetic/);
  assert.doesNotMatch(html,/adapter executed in AURA|Native read completed|native discovery evidence/);
});

test('supporting tools and approval backlog expand only when explicitly requested',()=>{
  for(const [focus,name] of [['google','Google Ads'],['mailchimp','Mailchimp'],['klaviyo','Klaviyo']]){
    const html=render(`?screen=results&focus=${focus}`);
    assert.ok(html.includes(`${name} interface preview`));
    assert.equal((html.match(/<details[^>]*\bopen(?:=|[ >])/g)||[]).length,1);
    assert.ok(html.indexOf('aria-label="Main campaign outcome"')<html.indexOf(`id="demo-${focus}"`));
  }
  const approvals=render('?screen=results&focus=approvals');
  for(const text of ['Implementation backlog','Supporting evidence','Expected learning','Approval needed'])assert.ok(approvals.includes(text));
  const measurement=render('?screen=results&focus=measurement');
  assert.match(measurement,/Do not add the platforms/);
  assert.match(measurement,/Attributed revenue/);
});

test('guided walkthrough covers AURA request, planning, review, playback and all supporting outputs',()=>{
  for(const phase of ['input','plan','review','execution'])assert.match(render(`?screen=${phase}`),new RegExp({input:'Create plan',plan:'Review inputs',review:'Play prepared workflow',execution:'no provider API calls'}[phase]));
  for(let i=0;i<tour.length;i++){
    const html=render(`?scene=${i}`);assert.ok(html.includes(tour[i].title));assert.match(html,/Guided marketing walkthrough/);
  }
  assert.equal(tour[0].phase,'results');assert.equal(tour.at(-1).phase,'results');
  assert.equal(sceneFromSearch('?scene=999'),-1);assert.equal(sceneFromSearch('?tour=1'),0);
  assert.match(render('?screen=unknown'),/Main campaign outcome/);
});

test('public demo carries only synthetic fixture data and excludes private accounts and live account code',()=>{
  assert.equal(tools.length,4);
  assert.equal(brief.google_drafts.length,2);assert.equal(brief.mailchimp_drafts.length,1);
  assert.equal(packets.meta.comparison.current.spend,2100);
  assert.equal(packets.klaviyo.comparison.current.orders,30);
  for(const key of ['meta','google','mailchimp','klaviyo'])assert.equal(toolState(key).mode,'Simulated');
  const packed=downloadPacket();assert.equal(packed.provider_api_called,false);assert.equal(packed.external_writes,false);
  assert.match(toolState('google').response.ret[0].value,/^SIM_/);
  assert.match(toolState('mailchimp').response.lists[0].id,/^SIM_/);
  assert.doesNotMatch(JSON.stringify(packed),/workspace_id|sourceRunId|oauth_access_token|client_secret|@gmail\.com/);
  const entry=fs.readFileSync(path.join(repo,'showcase/marketing-workflow/index.html'),'utf8');assert.match(entry,/connect-src 'none'/);
  const app=fs.readFileSync(path.join(repo,'src/showcase/marketing-workflow/ShowcaseApp.jsx'),'utf8');
  assert.doesNotMatch(app,/aura\.entities|fetch\(|createPythonRun|approvePythonPlan|getPythonRun/);
});
