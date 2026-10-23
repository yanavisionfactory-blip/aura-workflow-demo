import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {build} from 'vite';
import {unzipSync,strFromU8} from 'fflate';
import {applyDrafts,copyFields,simulateRevision,wordpressOutput,packageZip,readDrafts} from '../src/showcase/first-choice-seo/model.mjs';
import {tour} from '../src/showcase/first-choice-seo/scenario.mjs';
const repo=fileURLToPath(new URL('../',import.meta.url));const data=JSON.parse(fs.readFileSync(path.join(repo,'src/showcase/first-choice-seo/data.json'),'utf8'));let temp,render;
before(async()=>{temp=fs.mkdtempSync(path.join(repo,'.first-choice-render-'));await build({configFile:path.join(repo,'vite.first-choice.config.js'),logLevel:'silent',build:{ssr:path.join(repo,'tests/fixtures/firstChoiceRender.jsx'),outDir:temp,emptyOutDir:true,rollupOptions:{output:{entryFileNames:'render.mjs'}}},ssr:{noExternal:['lucide-react']}});({render}=await import(pathToFileURL(path.join(temp,'render.mjs'))));});
after(()=>{if(temp)fs.rmSync(temp,{recursive:true,force:true});});
test('public fixture is synthetic, distinct and free of private source material',()=>{
 assert.equal(data.simulation,true);assert.equal(data.articles.length,3);assert.equal(data.keywords.rows.length,12);assert.equal(data.keywords.totalIdeasReported,12);assert.equal(data.snapshotDate,'2026-10-23');
 assert.equal(new Set(data.articles.map(a=>a.body)).size,3);assert.match(data.source.provenance,/No private attachment/);
 for(const a of data.articles){assert.equal(a.status,'unpublished');assert.equal(a.approval,'pending');assert.match(a.notice,/fictional/i);assert.ok(a.body.length>2500);assert.equal(Object.keys(a.seo).length,3);assert.equal(a.sourcePages,undefined);}
 assert.ok(Object.values(data.keywords.localVolumeVerified).every(v=>v===false));assert.match(data.limits.join(' '),/Every keyword metric is simulated/);
 assert.doesNotMatch(JSON.stringify(data),/atlassian\.net|@firstchoiceseo|api_key|client_secret|workspace_id|wp-admin|sourcePages|review pack/);
});
test('local editing propagates to tool previews and exports while preserving the source snapshot',()=>{
 const before=JSON.stringify(data);const copy=simulateRevision(data.articles[0],'Make the introduction shorter');copy.title='<script>Local review title</script>';
 const packet=applyDrafts(data,{dallas:{...copy,status:'published',notice:'replacement'}});assert.equal(JSON.stringify(data),before);assert.equal(packet.articles[0].status,'unpublished');assert.equal(packet.articles[0].notice,data.articles[0].notice);assert.equal(packet.articles[0].approval,'pending');assert.ok(packet.articles[0].localRevision);assert.notEqual(packet.articles[0].version,undefined);
 assert.equal(wordpressOutput(packet).pages[0].title,copy.title);const zip=unzipSync(packageZip(packet));assert.deepEqual(JSON.parse(strFromU8(zip['source-snapshot.json'])),data);assert.equal(JSON.parse(strFromU8(zip['prepared-drafts.json'])).articles[0].title,copy.title);assert.match(strFromU8(zip['articles/dallas.html']),/&lt;script&gt;/);assert.doesNotMatch(strFromU8(zip['articles/dallas.html']),/<script>/);
 assert.equal(applyDrafts(data,{dallas:copyFields(data.articles[0])}).articles[0].localRevision,undefined);assert.throws(()=>simulateRevision(data.articles[0],'Promise guaranteed appointments'),/prepared editor supports/);assert.deepEqual(readDrafts({getItem:()=>'{bad'},data),{});
});
test('public result opens the main tool first and collapses every secondary tool',()=>{
 const html=render();assert.ok(html.indexOf('Primary WordPress output')<html.indexOf('Other tool outputs'));assert.match(html,/WordPress simulated tool screen/);assert.match(html,/Ask AURA/);assert.match(html,/Edit manually/);assert.equal(wordpressOutput(data).pages.length,3);assert.match(render('?screen=tool&tool=wordpress'),/Prepare three location articles/);
 for(const tool of ['planner','locations','rankmath','asana']){assert.ok(html.includes('?screen=tool&amp;tool='+tool));assert.match(render('?screen=tool&tool='+tool),/Simulated/);}
 assert.match(render('?screen=tool&tool=planner'),/not organic SEO difficulty/);assert.match(render('?screen=tool&tool=asana'),/No project, task, assignment or notification/);assert.match(render('?screen=sources'),/synthetic keyword data/i);
});
test('review and every guided scene are explicit prepared playback',()=>{
 assert.match(render('?screen=review'),/Approve &amp; run demo/);assert.doesNotMatch(render('?screen=review'),/Read-only steps/);assert.match(render('?screen=execution'),/No new provider calls/);
 for(let i=0;i<tour.length;i++){const html=render('?scene='+i);assert.ok(html.includes(tour[i].title));assert.match(html,/Guided walkthrough/);}
 assert.match(render('?screen=feedback'),/No email or form submission/);assert.match(render('?screen=video'),/walkthrough.mp4/);
 assert.match(fs.readFileSync(path.join(repo,'showcase/first-choice-seo/index.html'),'utf8'),/connect-src 'none'/);
});
