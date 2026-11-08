export const originalSheet = 'https://docs.google.com/spreadsheets/d/1M19njKrX9F3rEdzZL1BIM0kdi4Omf_tU-0njsBLxhtA/edit';

export const retryPrompt = `Compare my Google Ads and Reddit Ads campaign results in Google Sheets, then present the report in Canva.

Use the latest saved Google Ads response if a new request is rate-limited. Keep its original date coverage and retrieval time visible. For Reddit Ads, report 1–31 October 2026 and include active and inactive campaigns from the connected advertising account.

Include spend, impressions, clicks, CTR and CPC, with campaign-level detail and platform totals. Label conversion definitions and missing data. Do not rank platforms when date ranges or conversion definitions differ.

Save the spreadsheet and a four-slide presentation, then show both outputs for review.`;

// The successful corrected report, saved 8 November 2026. No live requests.
export const campaigns = [
  { platform:'Google Ads', name:'Campaign #1', status:'Enabled', spend:173.231853, impressions:8101, clicks:193, conversions:7, conversionType:'Platform conversions', period:'Full available history' },
  { platform:'Reddit Ads', name:'AURA pilot', status:'Paused', spend:32.915514, impressions:16054, clicks:69, conversions:0, conversionType:'Attributed purchases', period:'1–31 Oct 2026 UTC' },
  { platform:'Reddit Ads', name:'Lead Generation campaign', status:'Effectively paused', spend:31.759234, impressions:2436, clicks:10, conversions:0, conversionType:'Attributed purchases; leads unavailable', period:'1–31 Oct 2026 UTC' },
];
export const money = n => new Intl.NumberFormat('en-IE',{style:'currency',currency:'EUR'}).format(n);
export const integer = n => n.toLocaleString('en-US');
export const percent = n => (100*n).toFixed(2)+'%';
export function totals(platform) {
  return campaigns.filter(c=>c.platform===platform).reduce((a,c)=>({spend:a.spend+c.spend,impressions:a.impressions+c.impressions,clicks:a.clicks+c.clicks}),{spend:0,impressions:0,clicks:0});
}
const google=totals('Google Ads'), reddit=totals('Reddit Ads');
export const views = {
  summary:{title:'Google Ads + Reddit Ads',description:'The saved platform results, with the reporting periods kept visible.',headers:['Metric','Google Ads','Reddit Ads'],widths:[34,33,33],rows:[
    ['Spend',money(google.spend),money(reddit.spend)],['Impressions',integer(google.impressions),integer(reddit.impressions)],['Clicks',integer(google.clicks),integer(reddit.clicks)],['CTR',percent(google.clicks/google.impressions),percent(reddit.clicks/reddit.impressions)],['CPC',money(google.spend/google.clicks),money(reddit.spend/reddit.clicks)],['Reporting period','Full available history','1–31 October 2026 · UTC']
  ],note:'Different reporting periods prevent a like-for-like performance ranking. Google uses its saved full-history response; Reddit covers October 2026.'},
  campaigns:{title:'Three campaign records',description:'The Reddit total includes AURA pilot and the Lead Generation campaign.',headers:['Campaign','Platform / status','Spend','Impressions','Clicks','CPC'],widths:[24,25,13,14,10,14],rows:campaigns.map(c=>[c.name,c.platform+' · '+c.status,money(c.spend),integer(c.impressions),integer(c.clicks),money(c.spend/c.clicks)]),note:'AURA pilot matches the screenshot: €32.92, 16,054 impressions and 69 clicks. Totals use exact values before rounding, so rounded campaign spend can differ from the total by €0.01.'},
  coverage:{title:'Dates, conversions and coverage',description:'The context that travels with the spreadsheet and presentation.',headers:['Field','Google Ads','Reddit Ads'],widths:[28,36,36],rows:[
    ['Source saved','8 Nov 2026 · 08:41 UTC','8 Nov 2026 · 18:18 UTC'],['Reporting period','Full available history; exact first/last delivery dates unavailable','1–31 Oct 2026 UTC (exclusive API end: 1 Nov)'],['Conversions','7 platform-reported conversions','0 attributed purchases'],['Conversion value','€7 platform-reported value; not verified sales revenue','€0 attributed purchase value'],['Cost per conversion','€24.75 per platform conversion','Unavailable — no attributed purchases'],['Lead count','Not established','Unavailable — leads were not requested'],['Source handling','Earlier saved response reused after an API limit','Corrected Reddit account connection'],['Campaign coverage','1 campaign; no date or status filter','2 campaigns; active and inactive included']
  ],note:'Missing data is not zero. Conversion definitions and attribution windows are not aligned, so conversions are not combined or ranked.'},
  source:{title:'Exact saved campaign values',description:'Unrounded source values used for the calculations above. A compact export of this report’s campaign records.',headers:['Platform','Campaign','Spend EUR','Impressions','Clicks','Conversions / definition'],widths:[14,26,16,13,10,21],rows:campaigns.map(c=>[c.platform,c.name,String(c.spend),String(c.impressions),String(c.clicks),c.conversions+' · '+c.conversionType]),note:'These are saved report values, not a live spreadsheet connection. The original workbook retains its existing permissions.'}
};
export const slideTitles = ['Platform overview','Google Ads campaign','Reddit Ads campaigns','Coverage and definitions'];
export const stages = [
  {title:'Describe the result you need',subtitle:'The reporting request, condensed for this walkthrough.',body:'Compare my Google Ads and Reddit Ads campaign stats in a Google Sheet, then present the results in Canva.',note:'This example uses Yana’s saved reporting run. It is not a claim that Elias’s account ran this workflow.',kind:'prompt'},
  {title:'Review the reporting workflow',subtitle:'Sources → report → presentation',steps:[['Google Sheets','Prepare the report workbook'],['Google Ads','Use the saved campaign response'],['Reddit Ads','Read the corrected account’s October results'],['Google Sheets','Write campaign rows, totals and source notes'],['Canva','Prepare the four-slide presentation'],['AURA','Collect the saved outputs for review']],note:'A walkthrough of the completed reporting process, including the assisted recovery.',kind:'plan'},
  {title:'Continue with the saved information',subtitle:'The source issue is visible in the result.',steps:[['Google Ads · Saved data reused','A fresh request hit an API limit. The earlier response provides 1 campaign, €173.23 spent and 193 clicks.'],['Reddit Ads · Connection corrected','The earlier connection used a different login/account. The corrected response contains 2 campaigns, €64.67 spent and 79 clicks.'],['Google Sheets · Report saved','Campaign rows and derived metrics were regenerated with date and conversion notes.'],['Canva · Presentation saved','The corrected four-slide presentation was saved and its output collected in AURA.']],note:'This is a saved walkthrough. Advancing it does not execute AURA or make advertising API requests.',kind:'run'},
  {title:'Workflow results are ready to inspect',subtitle:'The saved report and presentation are shown on this page.',steps:[['Google Sheets','Platform totals, campaign records and coverage notes.'],['Canva','Four saved slides and the presentation export.']],note:'This run was completed with assistance and saved-data reuse. It does not demonstrate a new unattended execution.',kind:'result'}
];
