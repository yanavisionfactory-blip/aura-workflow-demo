import fixture from '../../data/marketing_tools_maple_ember_v1.json' with {type:'json'};

export const brief=structuredClone(fixture.brief);
brief.native_limit='This public demo uses fictional accounts only. Before a live implementation, verify the same-client accounts, consent, conversion events, destinations and approvals.';
brief.native_proposals_note='Prepared proposals from the fictional client brief. No live account discovery or provider writes occur in this demo. Verify the client account, products, offers, tracking, consent, copy and test design before implementation.';

function preparedPacket(key) {
  const source=structuredClone(fixture[key]);
  const comparison={};
  for(const period of ['previous','current']) {
    const metrics=key==='meta'?['spend','purchases','revenue']:['delivered','clicks','orders','revenue','unsubscribes'];
    const rows=source.rows.filter(row=>row.period===period);
    const totals=Object.fromEntries(metrics.map(metric=>[metric,rows.reduce((sum,row)=>sum+row[metric],0)]));
    if(key==='meta')totals.purchase_cpa=totals.purchases?totals.spend/totals.purchases:null;
    else for(const metric of ['clicks','unsubscribes'])totals[metric+'_rate']=totals.delivered?totals[metric]/totals.delivered:null;
    comparison[period]=totals;
  }
  return {...source,kind:'marketing_tool',synthetic:true,scenario:'public_marketing_walkthrough',
    brief,periods:structuredClone(fixture.periods),timezone:'America/New_York',currency:'USD',comparison,
    receipt:{mode:'prepared_public_demo',source:'marketing_tools_maple_ember_v1.json',
      provider_api_called:false,external_writes:false,native_drafts_saved:false}};
}

export const packets={meta:preparedPacket('meta'),klaviyo:preparedPacket('klaviyo')};
export const tools=[
  {key:'meta',name:'Meta Ads',role:'Paid acquisition · main creative outcome',operation:'demo.meta-ads.prepare-creative',
    output:'Two ad concepts, primary text, headlines, calls to action and a proposed creative test.'},
  {key:'google',name:'Google Ads',role:'Supporting acquisition test',operation:'demo.google-ads.prepare-search-copy',
    output:'Two responsive search ad variations using the same offer and landing page.'},
  {key:'mailchimp',name:'Mailchimp',role:'Permissioned prospect nurture',operation:'demo.mailchimp.prepare-invitation',
    output:'One invitation with two subject lines, a tracked CTA and purchaser/checkout exclusions.'},
  {key:'klaviyo',name:'Klaviyo',role:'Recovery and repeat purchase',operation:'demo.klaviyo.prepare-lifecycle',
    output:'Checkout recovery and replenishment proposals with triggers, timing and suppression rules.'},
];
export function toolState(key) {
  const tool=tools.find(item=>item.key===key);
  if(!tool)return null;
  return {...tool,mode:'Simulated',status:'completed',label:'Prepared simulation · no provider calls',
    response:packets[key] || {synthetic:true,
      ...(key==='google'?{ret:[{label:'Maple & Ember Coffee · fictional account',value:'SIM_GOOGLE_MAPLE_EMBER'}]}:
        {lists:[{id:'SIM_MAILCHIMP_MAPLE_EMBER',name:'Maple & Ember · fictional audience',stats:{member_count:600}}]}),
      receipt:{mode:'prepared_public_demo',provider_api_called:false,external_writes:false}},
  };
}

export const approvals=[
  {platform:'Meta Ads',priority:'1',action:packets.meta.test.action,evidence:'Static CPA $50 → $91.67; frequency 2 → 4. Simulated source rows META_1_1 and META_2_1.',learning:packets.meta.test.learning,approval:packets.meta.test.approval},
  {platform:'Google Ads',priority:'2',action:'Review the two Search variations and confirm keyword intent, purchase conversion and proposed test settings.',evidence:'Approved fictional House Blend facts, WELCOME10 and the shared .example destination.',learning:'Which approved message attracts qualified first-purchase traffic.',approval:'Same-client account, live destination/tracking, copy, targeting, conversion definition and test budget.'},
  {platform:'Mailchimp',priority:'3',action:'Review the invitation for permissioned non-purchasers without an active checkout.',evidence:brief.mailchimp_drafts[0].eligibility,learning:'Whether the invitation helps eligible prospects place a first order.',approval:'Audience consent, purchaser/checkout exclusions, cross-platform synchronization, sender, footer and copy.'},
  {platform:'Klaviyo',priority:'4',action:packets.klaviyo.test.action,evidence:'Checkout message orders/delivered 30/410 → 24/420. Replenishment has zero historical sends.',learning:packets.klaviyo.test.learning,approval:packets.klaviyo.test.approval},
];

export function downloadPacket() {
  return {kind:'prepared_public_marketing_demo',synthetic:true,client:brief.client,brief,
    tools:tools.map(tool=>({...tool,state:toolState(tool.key),packet:packets[tool.key] || null})),
    approvals,provider_api_called:false,external_writes:false};
}
