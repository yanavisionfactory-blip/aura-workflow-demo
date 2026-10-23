import test from 'node:test';
import assert from 'node:assert/strict';
import data from '../src/showcase/website-content/data.mjs';
import {editableCopy,cleanCopy,applyEdits,simulateEdit,readEdits,storageKey} from '../src/showcase/website-content/contentEdits.mjs';
import {websiteCMSPreview} from '../src/lib/websiteCMSPreview.mjs';
import {pageHTML} from '../src/lib/websiteContentExport.mjs';
test('local edits propagate to all tool screens and the handoff while resetting approval',()=>{
 const original=JSON.stringify(data);const page=data.pages[0];const copy=simulateEdit(page,'Make it shorter and clearer; change the button');
 const changed=applyEdits(data,{p01:{...copy,url:'https://bad.invalid',approval:{status:'approved'},original:{excerpt:'replacement'}}});
 assert.equal(JSON.stringify(data),original);assert.notEqual(changed.pages[0].version,page.version);assert.equal(changed.pages[0].source_version,page.version);
 assert.deepEqual(changed.pages[0].original,page.original);assert.equal(changed.pages[0].url,page.url);assert.equal(changed.pages[0].cta_target,page.cta_target);
 assert.deepEqual(changed.pages[0].approval,{status:'pending',reviewer:null,evidence:null,reviewed_at:null});assert.equal(changed.pages[0].cms_draft,null);
 for(const tool of websiteCMSPreview(changed).tools){assert.equal(tool.pages[0].title,copy.h1);assert.equal(tool.pages[0].content_blocks[0].body,copy.sections[0].body);assert.equal(tool.remote_records_created,0);}
 assert.ok(pageHTML(changed.pages[0]).includes(copy.h1));assert.deepEqual(changed.pages[1],data.pages[1]);
 assert.equal(applyEdits(data,{p01:editableCopy(page)}).pages[0].version,page.version);
 assert.equal(applyEdits(data,{p01:copy}).pages[0].version,changed.pages[0].version);
});
test('unsupported or invalid instructions cannot silently create a simulated revision',()=>{
 assert.throws(()=>simulateEdit(data.pages[0],'Add a guaranteed score improvement'),/simulated editor supports/);
 assert.throws(()=>cleanCopy(data.pages[0],{...editableCopy(data.pages[0]),sections:[]}),/all four/);
 assert.throws(()=>cleanCopy(data.pages[0],{...editableCopy(data.pages[0]),h1:''}),/Complete/);
 for(const page of data.pages){const revised=simulateEdit(page,'Make it warmer for parents');assert.equal(revised.sections.length,4);assert.equal(revised.sections[1].body,page.sections[1].body);}
 assert.equal(simulateEdit(data.pages[0],'Change heading to "Support for Your Student"').h1,'Support for Your Student');
});
test('local storage accepts only recognized page copy and tolerates blocked or damaged storage',()=>{
 const copy=simulateEdit(data.pages[0],'Make it shorter');const saved=readEdits({getItem:key=>{assert.equal(key,storageKey);return JSON.stringify({p01:copy,foreign:{secret:'x'}});}},data);
 assert.deepEqual(Object.keys(saved),['p01']);assert.deepEqual(readEdits({getItem:()=>'{bad'},data),{});assert.deepEqual(readEdits({getItem:()=>{throw Error('Blocked');}},data),{});
});
