import {leads,posts} from './data.mjs';

export const replyFor=lead=>`Hi ${lead.name.split(' ')[0]}, thanks for reaching out. ${lead.id==='EC-103'?'Helping a technical team make its value clear to the right buyers is a useful starting point.':'It would help to understand the decision your team needs to make.'} Could you share your target audience, the main business problem and the timing you have in mind? I can then suggest whether a short discovery conversation makes sense.\n\nDiana`;
export const socialReplyFor=l=>l.category==='Media'?`Hi ${l.name.split(' ')[0]}, thank you for the editorial request. Could you share the outlet, topic, deadline and how the comment would be used? Diana can then review whether to contribute.`:l.category==='Partnership'?`Hi ${l.name.split(' ')[0]}, thanks for the invitation. Could you share the audience, proposed format and responsibilities for the roundtable? Diana will review whether it is a good fit.`:l.category==='Influencer'?`Hi ${l.name.split(' ')[0]}, thanks for reaching out. Please share your audience, proposed collaboration and commercial terms so Diana can review the fit.`:replyFor(l);

export const actionDrafts=[
 ...leads.map(l=>({id:'social-'+l.id,channel:l.source.startsWith('Facebook')?'meta':'linkedin',view:'inbox',recordId:l.id,label:'Reply to '+l.name,recipient:l.name+' · '+(l.source.startsWith('Facebook')?'Meta Business Suite':'LinkedIn'),text:socialReplyFor(l)})),
 {id:'email-Reply',channel:'gmail',kind:'Reply',label:'Reply to Nina',recipient:leads[2].email,subject:'Re: Content and positioning inquiry',text:replyFor(leads[2])},
 {id:'email-Proposal',channel:'gmail',kind:'Proposal',label:'Proposal for Maya',recipient:leads[0].email,subject:'Proposal v2 · illustrative scope',text:'Hi Maya,\n\nFollowing our sample discovery discussion, here is proposal v2 for review: a positioning workshop, a message framework and six social drafts, with two review rounds over four weeks.\n\nThe illustrative fee is €2,400; payment timing, tax treatment and the final scope still require Diana’s approval for a live engagement. This demo is not an offer.\n\nPlease let me know whether the scope reflects your priorities.\n\nDiana'},
 {id:'email-Follow-up',channel:'gmail',kind:'Follow-up',label:'Follow-up for Maya',recipient:leads[0].email,subject:'Re: Proposed scope',text:'Hi Maya,\n\nFollowing up on the proposed scope. Is there anything you would like to clarify before deciding on next steps? We can review the deliverables together; I will confirm any change to scope or terms before updating the proposal.\n\nDiana'},
 {id:'calendar-invitation',channel:'calendar',label:'Discovery invitation',time:'2026-11-05T10:00',zone:'Europe/London',guests:'Diana (organizer) · nina@routewise.example',text:'Discuss Routewise’s audience, current positioning challenge, decision process and possible scope. This is a discovery conversation, with no commercial commitment.'},
 ...leads.map(l=>({id:'next-'+l.id,channel:'hubspot',recordId:l.id,nextAction:true,label:'Next action · '+l.company,text:l.next})),
 {id:'agreement-scope',channel:'docusign',label:'Agreement scope & terms',text:'Proposed deliverables\nOne positioning workshop, a message framework and six social drafts. Two review rounds over four weeks.\n\nIllustrative commercial terms\n€2,400 example fee. Payment schedule, taxes, cancellation, intellectual property and final legal terms require separate approval before a live agreement.\n\nVersion history\nv1: initial scope. v2: review rounds clarified after the sample negotiation. No automatic discount or acceptance.'},
 {id:'pilot-report',channel:'measurement',label:'Pilot report note',text:'Review relevant conversations and qualified opportunities separately from media, influencer and partnership requests. Compare the illustrative time log with active work, including review.\n\nKeep observed touchpoints and buyer-reported influences separately. The prepared agreement example does not prove that content caused a sale.'}
];
export const getDraft=id=>posts.find(p=>p.id===id)||actionDrafts.find(d=>d.id===id);
export const reviewScreens=[
 ...posts.map(p=>({draftId:p.id,tool:p.channel,postId:p.id,title:'Day '+p.day+' · '+p.label})),
 {draftId:'social-EC-101',tool:'linkedin',view:'inbox',recordId:'EC-101',title:'Contextual reply · Maya'},
 {draftId:'social-EC-102',tool:'meta',view:'inbox',recordId:'EC-102',title:'Contextual reply · Adam'},
 {draftId:'next-EC-101',tool:'hubspot',recordId:'EC-101',title:'Client record & next action'},
 {draftId:'email-Reply',tool:'gmail',kind:'Reply',title:'Discovery reply · Nina'},
 {draftId:'calendar-invitation',tool:'calendar',title:'Discovery invitation'},
 {draftId:'email-Proposal',tool:'gmail',kind:'Proposal',title:'Proposal · Maya'},
 {draftId:'email-Follow-up',tool:'gmail',kind:'Follow-up',title:'Proposal follow-up'},
 {draftId:'agreement-scope',tool:'docusign',title:'Agreement document & evidence'},
 {draftId:'pilot-report',tool:'measurement',title:'Pilot report'}
];
