import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {build} from 'vite';
import data from '../src/showcase/website-content/data.mjs';
import {tour,toolHref} from '../src/showcase/website-content/scenario.mjs';
const repo=fileURLToPath(new URL('../',import.meta.url));let temp,render;
before(async()=>{temp=fs.mkdtempSync(path.join(repo,'.website-showcase-render-'));await build({configFile:path.join(repo,'vite.website.config.js'),logLevel:'silent',build:{ssr:path.join(repo,'tests/fixtures/websiteShowcaseRender.jsx'),outDir:temp,emptyOutDir:true,rollupOptions:{output:{entryFileNames:'render.mjs'}}},ssr:{noExternal:['lucide-react']}});({render}=await import(pathToFileURL(path.join(temp,'render.mjs'))));});
after(()=>{if(temp)fs.rmSync(temp,{recursive:true,force:true});});
test('website demo preserves five complete copy drafts, historical evidence and pending approval',()=>{
 assert.equal(data.pages.length,5);assert.equal(data.sources.length,8);assert.equal(data.staging.drafts_created,0);
 assert.deepEqual(data.pages.map(p=>p.version),['a5a452bce876','c98c9953433e','e0f2a97b0d22','0579bf741eb2','33fba2202062']);
 for(const p of data.pages){assert.equal(p.sections.length,4);assert.equal(p.approval.status,'pending');assert.equal(p.approval.reviewer,null);assert.ok(p.assets.every(a=>a.approval_status==='pending'&&a.rights_status==='unverified'));}
 assert.doesNotMatch(JSON.stringify(data),/workspace_id|client_secret|shpss_|oauth_access_token|4903a714|8e0194b8/);
});
test('main result appears before per-tool entries with public links for all four CMS screens',()=>{
 const html=render();assert.ok(html.indexOf('Home revised page')<html.indexOf('Results by tool'));
 for(const provider of ['wordpress','shopify','woocommerce','bigcommerce']){assert.ok(html.includes(`?screen=tool&amp;tool=${provider}`));const screen=render(`?screen=tool&tool=${provider}`);assert.match(screen,/simulated tool screen/);assert.match(screen,/5 drafts/);for(const p of data.pages)assert.ok(!screen.includes(p.version));assert.match(screen,/Part of your task/);}
 assert.doesNotMatch(html,/href="\/runs\//);assert.equal(toolHref('unknown-preview'),null);
 assert.match(render('?screen=results&tab=Approvals'),/Choose a reviewer/);
 assert.match(render('?screen=results&tab=Developer%20handoff'),/create separate unpublished drafts/);
});
test('guided tour, input, review and playback remain explicit and offline',()=>{
 assert.match(render('?screen=input'),/Create plan/);assert.match(render('?screen=plan'),/Review before running/);
 assert.match(render('?screen=review'),/Start prepared demo/);assert.match(render('?screen=execution'),/No live provider calls/);
 for(let i=0;i<tour.length;i++){const html=render(`?scene=${i}`);assert.ok(html.includes(tour[i].title));assert.match(html,/Guided walkthrough/);}
 const feedback=render('?screen=feedback');assert.match(feedback,/No email or form submission is made/);assert.doesNotMatch(feedback,/<form|type="submit"/);
 assert.match(render('?screen=video'),/<video/);
 assert.match(render('?screen=video'),/walkthrough.mp4/);
 const entry=fs.readFileSync(path.join(repo,'showcase/website-content/index.html'),'utf8');assert.match(entry,/connect-src 'none'/);
});
