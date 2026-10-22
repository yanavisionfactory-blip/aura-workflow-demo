export const originalPrompt=`Run one coordinated acquisition and retention workflow for Maple & Ember Coffee using Google Ads, Meta Ads, Mailchimp and Klaviyo.

Compare the supplied weekly performance, select one supported campaign opportunity, and use the approved fictional products and offers consistently. Prepare paid ad variations, a permissioned prospect email, abandoned-checkout recovery and a repeat-purchase message.

Show the main creative outcome first in its tool screen. Keep the other outputs, source figures, coordination activity and approvals in collapsed dropdowns. Prepare drafts for review only; do not launch, publish, activate flows or send messages.`;

export const workflowSteps=[
  {tool:'Meta Ads',title:'Find the acquisition opportunity',action:'Compare the two synthetic weeks and prepare two creative concepts',output:'Static CPA rose from $50 to $91.67. Two matched creative proposals are ready.',riskLevel:'read'},
  {tool:'Google Ads',title:'Prepare matching Search ads',action:'Carry WELCOME10 and the shared destination into two Search variations',output:'Two responsive search ad drafts remain unsaved in the provider.',riskLevel:'read'},
  {tool:'Mailchimp',title:'Prepare prospect nurturing',action:'Draft a permissioned invitation and define checkout and purchaser exclusions',output:'Two subjects and one short invitation are prepared for the fictional prospect cohort.',riskLevel:'read'},
  {tool:'Klaviyo',title:'Prepare recovery and retention',action:'Define the checkout and repeat-purchase messages, triggers and suppression',output:'Two lifecycle proposals stay separate from the Mailchimp audience.',riskLevel:'read'},
  {tool:'AURA coordination',title:'Bring the tool outputs together',action:'Keep the main creative visible and organize supporting outputs for review',output:'The main outcome opens first. Every supporting section starts collapsed.',riskLevel:'read'},
];

export const tour=[
  {phase:'results',title:'Start with the main outcome',caption:'The finished ad creative is visible immediately in its Meta-style tool screen. Supporting work stays in closed dropdowns.',seconds:9},
  {phase:'input',title:'Describe one business outcome',caption:'Ask AURA to coordinate acquisition, prospect nurture, checkout recovery and repeat purchase across four tools.',seconds:7},
  {phase:'plan',title:'Review the coordinated plan',caption:'Each tool owns a specific action. AURA coordinates their inputs, offer, destination and audience boundaries.',seconds:8},
  {phase:'review',title:'Check the shared inputs',caption:'The prepared demo uses one fictional client, synthetic accounts, fixed reporting weeks and scenario-approved offers. Nothing is connected or sent.',seconds:8},
  {phase:'execution',title:'Follow AURA’s coordination',caption:'This is prepared local playback. The four tool outputs remain separate and no provider API is called.',seconds:9},
  {phase:'results',title:'Return to the actual creative',caption:'Inspect the primary text, headline, call to action and Facebook feed preview. Change the draft selector to compare the two proposals.',seconds:9},
  {phase:'results',focus:'google',title:'Expand the Search ad drafts',caption:'Google Ads supports the same offer and destination. Two Search variations are available in an imitated editor, inside this dropdown.',seconds:9},
  {phase:'results',focus:'mailchimp',title:'Expand the prospect invitation',caption:'Mailchimp owns permissioned zero-order prospects without active checkout. The email includes subject options, copy and a tracked CTA.',seconds:9},
  {phase:'results',focus:'klaviyo',title:'Expand checkout and repeat purchase',caption:'Klaviyo owns checkout and customer lifecycle. Preview the proposed flows and messages without creating or activating anything.',seconds:10},
  {phase:'results',focus:'coordination',title:'See how the tools fit together',caption:'A purchase exits prospect messaging; active checkout takes priority; consent and global suppression override all sends.',seconds:8},
  {phase:'results',focus:'approvals',title:'Review the implementation backlog',caption:'Every proposed task names its platform, evidence, expected learning and required approval. All proposals remain unlaunched.',seconds:8},
  {phase:'results',title:'Finish on the main outcome',caption:'The creative remains the first thing you see. Return to any supporting dropdown when you need more detail.',seconds:8},
];
export const validPhases=new Set(['results','input','plan','review','execution']);
export function sceneFromSearch(search) {
  const params=new URLSearchParams(search);
  if(params.has('scene')){
    const index=Number(params.get('scene'));
    if(Number.isInteger(index)&&tour[index])return index;
  }
  return params.get('tour')==='1'?0:-1;
}
export function executionSteps(completed) {
  return workflowSteps.map((item,index)=>({...item,status:index<completed?'completed':index===completed?'running':'pending',liveOutput:index<completed?item.output:''}));
}
