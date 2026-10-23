import test from 'node:test';
import assert from 'node:assert/strict';
import {leads,posts,sampleEnvelope,timeLog,sources} from '../src/showcase/easy-communications/data.mjs';
import {approvePost,editPost,initialState,isApproved,packageText,publishPost,replyAllowed,restoreState,summary,timeSummary,verifyEnvelope} from '../src/showcase/easy-communications/model.mjs';

test('a changed social draft cannot inherit approval or be published',()=>{
 const post=posts[0],approved=approvePost(initialState(),post);
 assert.equal(isApproved(post,approved),true);
 assert.equal(publishPost(approved,post).postStates[post.id],'published');
 const revised=editPost(approved,post.id,'A different point of view for review.');
 assert.equal(isApproved(post,revised),false);
 assert.throws(()=>publishPost(revised,post),/Approve the exact current text/);
 assert.equal(publishPost(approvePost(revised,post),post).postStates[post.id],'published');
});
test('Quora stays a manual handoff even after draft approval',()=>{
 const post=posts.find(p=>p.channel==='quora');
 assert.throws(()=>publishPost(approvePost(initialState(),post),post),/manual handoff/);
});
test('reply approval is bound to both recipient and exact message',()=>{
 const approved={recipient:'nina@routewise.example',message:'Could we discuss your brief?',approvedRecipient:'nina@routewise.example',approvedMessage:'Could we discuss your brief?'};
 assert.equal(replyAllowed(approved),true);
 assert.equal(replyAllowed({...approved,recipient:'someone-else@example.com'}),false);
 assert.equal(replyAllowed({...approved,message:'A new commercial commitment.'}),false);
 assert.equal(replyAllowed({...approved,approvedMessage:''}),false);
});
test('sent, partly signed and evidence-incomplete envelopes do not count',()=>{
 assert.equal(verifyEnvelope(sampleEnvelope),true);
 for(const incomplete of [{status:'sent'},{verified:false},{certificate:false},{finalDocument:false},{signers:[{status:'completed'},{status:'sent'}]}]){
  const e={...sampleEnvelope,...incomplete};assert.equal(verifyEnvelope(e),false);assert.equal(summary(leads,e).signed,0);
 }
});
test('non-client inquiries cannot inflate qualification or conversion totals',()=>{
 assert.deepEqual(summary(),{conversations:8,business:5,qualified:3,meetings:2,proposals:1,signed:1,other:3});
 const falseSales=leads.map(l=>l.category==='Client inquiry'?l:{...l,qualified:true,meeting:true,proposal:true,agreement:true});
 assert.deepEqual(summary(falseSales),summary());
});
test('time savings include active review and have a reconstructable baseline',()=>{
 assert.deepEqual(timeSummary(timeLog),{baseline:270,active:108,saved:162});
 assert.equal(timeSummary([{baseline:5,active:10}]).saved,-5);
});
test('saved choices are restored conservatively and malformed state is safe',()=>{
 assert.deepEqual(restoreState('not json'),initialState());
 const restored=restoreState(JSON.stringify({measurement:'existing',crm:'aura',postEdits:[],postApprovals:null,events:['safe',{}]}));
 assert.equal(restored.crm,'aura');assert.equal(restored.measurement,'existing');assert.deepEqual(restored.postEdits,{});assert.deepEqual(restored.events,['safe']);
});
test('download preserves edited copy, source history and synthetic outcome labels',()=>{
 const state=editPost({...initialState(),measurement:'existing',crm:'aura'},posts[0].id,'Approved source material, revised draft.');
 const result=JSON.parse(packageText(state));
 assert.match(result.label,/SIMULATED/);assert.equal(result.posts[0].text,'Approved source material, revised draft.');assert.equal(result.posts[0].exactRevisionApproved,false);
 assert.equal(result.primaryLeadRecord,'aura');assert.equal(result.measurement,'existing');assert.equal(result.leads[0].selfReport,leads[0].selfReport);assert.equal(result.sources[0].url,sources[0].url);assert.match(result.attribution,/No causal/);
});

test('review covers each content draft and every workflow tool without selector state',async()=>{
 const {reviewScreens}=await import('../src/showcase/easy-communications/drafts.mjs');
 assert.deepEqual(reviewScreens.filter(s=>s.postId).map(s=>s.postId),posts.map(p=>p.id));
 for(const tool of ['linkedin','meta','quora','hubspot','gmail','calendar','docusign','measurement'])assert.ok(reviewScreens.some(s=>s.tool===tool),tool);
 assert.equal(new Set(reviewScreens.map(s=>s.draftId)).size,reviewScreens.length);
});
test('edits share the same draft across preview, tool, reload and export',async()=>{
 const {getDraft}=await import('../src/showcase/easy-communications/drafts.mjs');
 const {draftText,editDraft,editDraftField,draftField,draftVersion}=await import('../src/showcase/easy-communications/model.mjs');
 let state=initialState();
 for(const id of ['social-EC-101','email-Proposal','calendar-invitation','next-EC-101','agreement-scope','pilot-report']){
  state=editDraft(state,id,'Revised '+id);
  assert.equal(draftText(getDraft(id),state),'Revised '+id);
  assert.equal(draftVersion(state,id),1);
 }
 state=editDraftField(state,'email-Proposal','subject','Revised scope for review');
 const restored=restoreState(JSON.stringify(state));
 assert.equal(draftField(getDraft('email-Proposal'),restored,'subject'),'Revised scope for review');
 assert.equal(draftVersion(restored,'email-Proposal'),2);
 const exported=JSON.parse(packageText(restored));
 for(const id of ['social-EC-101','email-Proposal','calendar-invitation','next-EC-101','agreement-scope','pilot-report'])assert.equal(exported.drafts.find(d=>d.id===id).text,'Revised '+id);
 assert.deepEqual(exported.metrics,summary());
 assert.throws(()=>editDraft(state,'unknown','Text'),/Unknown draft/);
 assert.throws(()=>editDraftField(state,'email-Proposal','certificate','verified'),/Invalid draft field/);
});
test('a revised agreement cannot inherit historical completion evidence',async()=>{
 const {editDraft,verifyCurrentAgreement}=await import('../src/showcase/easy-communications/model.mjs');
 const state=editDraft(initialState(),'agreement-scope','A revised scope awaiting review.');
 assert.equal(verifyCurrentAgreement(initialState()),true);
 assert.equal(verifyCurrentAgreement(state),false);
 assert.equal(summary().signed,1);
});
