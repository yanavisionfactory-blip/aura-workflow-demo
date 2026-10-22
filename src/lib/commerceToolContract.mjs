import { BRIEF, PERIODS, TOOLS, simulationInputs, executeTool } from './commerceSimulation.mjs';

export const COMMERCE_ORDER = ['seller', 'google', 'meta', 'amazon'];
export const COMMERCE_TOOLS = {
  seller: { name: 'Amazon Seller Central', operation: 'seller_central_weekly_review' },
  google: { name: 'Google Ads', operation: 'google_ads_weekly_review' },
  meta: { name: 'Meta Ads Manager', operation: 'meta_ads_weekly_review' },
  amazon: { name: 'Amazon Ads', operation: 'amazon_ads_weekly_review' },
};
export const COMMERCE_ARGS = Object.freeze({ simulate: true, scenario: 'harbor_field_mug_v1', asin: BRIEF.asin, currency: 'USD' });
export const COMMERCE_SCHEMA = { type: 'object', additionalProperties: false, required: Object.keys(COMMERCE_ARGS), properties: Object.fromEntries(Object.entries(COMMERCE_ARGS).map(([key, value]) => [key, { type: typeof value === 'boolean' ? 'boolean' : 'string', enum: [value] }])) };
const must = (ok, message) => { if (!ok) throw new Error(message); };
export function validCommerceArguments(args) {
  return args && Object.keys(args).length === 4 && Object.entries(COMMERCE_ARGS).every(([key, value]) => args[key] === value);
}
const money = n => '$' + n.toFixed(2);
const percent = n => (n * 100).toFixed(2) + '%';

// Called by each remote MCP tool, never by the AURA browser as a fallback.
export async function commerceToolResponse(key, args, baseUrl) {
  must(COMMERCE_ORDER.includes(key) && validCommerceArguments(args), 'Only the explicitly authorized simulated product and reporting scenario are supported.');
  const input = simulationInputs('low')[key];
  const analysis = await executeTool(input);
  const tool = COMMERCE_TOOLS[key];
  const common = 'Draft for account-manager review. Validate real facts, tracking, rights and actual account settings. Keep total budget fixed. Set sample size, power, practical effect and stopping rule before setup. Run at least two full weeks and wait for the source attribution window plus reporting lag; this weekly comparison establishes no causal lift.';
  let test = null, copy = null;
  if (key === 'seller') copy = { title: 'Harbor & Field Everyday Travel Mug, 16 oz Stainless Steel Reusable Cup with Fitted Lid', bullets: ['16 oz reusable stainless steel mug for everyday use.', 'Includes a fitted lid for the mug.', 'Hand-wash the mug and lid.'] };
  if (key === 'google') {
    const queries = input.rows.filter(r => r.period === 'current' && r.report === 'search_terms');
    const ranked = [...queries].sort((a,b) => a.spend/a.purchases-b.spend/b.purchases);
    const best = ranked[0], weak = ranked.at(-1);
    test = { title: 'Product-specific Search headline', campaign: 'SIM Nonbrand Search', evidence: ['G-C-N', best.id, weak.id], observation: `${weak.entity}: ${money(weak.spend/weak.purchases)} CPA; ${best.entity}: ${money(best.spend/best.purchases)} CPA. This is observational query evidence.`, change: 'Compare the current lead headline “Make It Part of Your Routine” with “Reusable 16 oz Steel Mug”. Hold queries, bids, audience, landing page and total budget fixed. Use mutually exclusive 50/50 allocation if the actual account supports it; verify responsive-ad asset pinning/eligibility.', learning: `Can a product-specific lead headline improve Google purchase-credit CPA toward ${money(BRIEF.targets.googleCpa)}?`, metric: 'Google purchase-credit CPA; guardrails: purchase-credit rate, attributed value/cost and traffic balance.', approval: 'Account manager: copy/facts, purchase event, experiment support, allocation and sample/stopping plan. Website stock pool and independent store orders are missing.', design: common };
    copy = { headlines: ['Reusable 16 oz Steel Mug', 'Reusable Mug With Lid'], description: '16 oz stainless steel travel mug with fitted lid for everyday routine use.' };
  }
  if (key === 'meta') {
    const rows = input.rows.filter(r => r.period === 'current');
    const staticAd = rows.find(r => r.id === 'M-C-STATIC'), video = rows.find(r => r.id === 'M-C-VIDEO');
    test = { title: 'Product demonstration versus lifestyle static', campaign: 'SIM Mug Prospecting', evidence: rows.map(r => r.id), observation: `Static lifestyle CPA ${money(staticAd.spend/staticAd.purchases)}; product demonstration CPA ${money(video.spend/video.purchases)}. Delivery and audience differences may confound the comparison.`, change: 'Test a new product-demo concept against lifestyle static with mutually exclusive randomized 50/50 audiences if supported. Fix primary text 1 and the headline below in both arms; keep audience, placements, purchase event and total budget fixed. Primary text 2 is a separate review option.', learning: `Does showing the capacity, steel body and fitted lid improve Meta purchase CPA toward ${money(BRIEF.targets.metaCpa)}?`, metric: 'Meta purchase CPA; guardrails: link CTR, frequency, attributed value and store-order validation.', approval: 'Account manager: two assets, rights, claims, tracking and sample/stopping plan. Website stock pool, independent orders and mature attribution are missing.', design: common };
    copy = { primary: ['A reusable 16 oz stainless steel mug with fitted lid for everyday travel.', 'Simple, reusable, and ready for daily coffee moments — with a fitted lid and 16 oz capacity.'], headline: 'Everyday Travel Mug', brief: '15-second vertical and square product demonstration: open on the mug; show steel body and fitted lid with the mug upright; finish with an end card. Overlay “16 oz. Stainless steel. Fitted lid.” Add readable captions and CTA “Explore the mug”. Product imagery and usage rights require approval. Do not imply leakproofing, heat retention, dishwasher safety, health or environmental benefits.' };
  }
  if (key === 'amazon') {
    const queries = input.rows.filter(r => r.period === 'current' && r.report === 'search_terms');
    const ranked = [...queries].sort((a,b) => a.spend/a.sales-b.spend/b.sales), best = ranked[0], weak = ranked.at(-1);
    test = { title: 'Exact targeting for product-matched intent', campaign: 'SIM SP Mug Auto → SIM SP Mug Manual / ' + BRIEF.asin, evidence: [best.id, weak.id, 'A-C-AUTO', 'S-STOCK'], observation: `${best.entity}: ${percent(best.spend/best.sales)} ACoS; ${weak.entity}: ${percent(weak.spend/weak.sales)} ACoS.`, change: `After inventory/listing clearance, propose exact keyword “${best.entity}” in Manual and negative-exact routing of that same query in Auto, subject to bid-cap and isolation approval. Match weekdays and attribution maturity to the baseline; retain an unchanged comparable targeting control. Keep ASIN, listing, placement and total budget fixed. This is a directional, nonrandomized routing pilot, not proof of removing ceramic-query waste.`, learning: `Can exact-query control keep advertised-ASIN ACoS below ${percent(BRIEF.targets.amazonAcos)} while retaining attributed orders?`, metric: 'Advertised-ASIN ACoS and attributed orders; guardrails: total ASIN units, available stock and Featured Offer share.', approval: 'HOLD additional Amazon promotion until Seller Central verifies ≥14 days of available cover and listing clearance. Account manager must approve targeting, bid cap, routing, baseline/control and sample/stopping plan.', design: common };
  }
  const receipt = { ...analysis.receipt, operation: tool.operation, executor: tool.name + ' simulated MCP connector', execution_location: 'Render', mode: 'server_simulated_tool_adapter', vendor_api_called: false, provider_api_called: false, external_writes: false, native_drafts_saved: false };
  const source_url = baseUrl + '/reports/' + key;
  return { kind: 'commerce_tool', schema_version: 1, tool_key: key, tool: tool.name, synthetic: true, simulated: true, brief: BRIEF, periods: PERIODS, definitions: input.definitions, source_rows: input.rows, listing: input.listing || null, comparison: analysis.comparison, readiness: analysis.readiness, test, copy, source_url, receipt, status: 'draft', disclosure: 'Simulated tool response. Executed by a separately connected MCP tool through AURA. No Google, Meta or Amazon vendor API was called. No campaign, budget, listing or inventory was changed.' };
}

export function commerceRunSteps(connections, plan = null) {
  const keys = Object.fromEntries(COMMERCE_ORDER.map(key => [key, plan?.steps?.find(step => step.operation === COMMERCE_TOOLS[key].operation)?.key || key]));
  return COMMERCE_ORDER.map(key => ({ key: keys[key], agent: COMMERCE_TOOLS[key].name + ' reviewer', tool_slug: connections[key].slug, operation: COMMERCE_TOOLS[key].operation, arguments: { ...COMMERCE_ARGS }, depends_on: key === 'seller' ? [] : [keys.seller], reason: key === 'seller' ? 'Check product listing, traffic, total ASIN sales and available stock before promotion.' : 'Compare both complete weeks and prepare this platform’s evidence-linked test and copy for review.', expected_output: 'Explicitly simulated source rows, weekly calculations, attribution definitions, draft proposal and execution receipt.', consequential: true }));
}
export function validateCommercePlan(plan, connections) {
  must(plan?.steps?.length === 4, 'The plan must contain exactly the four requested tool operations. No additional operation was approved.');
  const expected = new Map(COMMERCE_ORDER.map(key => [COMMERCE_TOOLS[key].operation, connections[key].slug]));
  for (const step of plan.steps) {
    must(expected.get(step.operation) === step.tool_slug && !step.fallback_operation && !step.fallback_tool_slug && !step.condition, 'The proposed plan contains an unapproved tool or fallback.');
    expected.delete(step.operation);
  }
  must(!expected.size, 'A required tool operation is missing.');
}
export function commerceSourcesFromRun(run, connections) {
  must(run.status === 'completed' && run.steps?.length === 4, 'Only a completed four-tool native run can become this package; extra or incomplete steps are rejected.');
  const sources = {}, activity = [];
  for (const key of COMMERCE_ORDER) {
    const step = (run.steps || []).find(s => s.operation === COMMERCE_TOOLS[key].operation && s.tool_slug === connections[key].slug);
    must(step?.status === 'completed', COMMERCE_TOOLS[key].name + ' has no completed native execution.');
    const result = step.output?.provider_result;
    const source = result?.structured_content;
    must(!result?.is_error && result?.schema_validation?.status === 'passed' && source?.tool_key === key && source.synthetic === true && source.receipt?.mode === 'server_simulated_tool_adapter' && source.receipt?.execution_location === 'Render' && source.receipt?.operation === COMMERCE_TOOLS[key].operation && source.receipt?.external_writes === false, 'A valid remote tool receipt is required for ' + COMMERCE_TOOLS[key].name);
    must(JSON.stringify(source.periods) === JSON.stringify(PERIODS) && source.brief?.currency === 'USD' && source.brief?.timezone === 'America/Chicago', 'Reporting periods, currency and timezone must align.');
    sources[key] = source;
    activity.push({ id: step.id, key, tool: COMMERCE_TOOLS[key].name, operation: step.operation, status: step.status, started_at: step.started_at, completed_at: step.completed_at, input: step.arguments, output: step.output });
  }
  const seller = run.steps.find(s => s.operation === COMMERCE_TOOLS.seller.operation);
  must(COMMERCE_ORDER.slice(1).every(key => { const s = run.steps.find(s => s.operation === COMMERCE_TOOLS[key].operation); return new Date(s.started_at) >= new Date(seller.completed_at); }), 'Seller Central must finish before advertising reviews start.');
  return { sources, activity };
}
export function buildCommerceDelivery(run, connections) {
  const { sources, activity } = commerceSourcesFromRun(run, connections);
  return { kind: 'commerce_tools', schemaVersion: 1, title: 'Unstoprev — weekly marketing action package', agency: 'Unstoprev', client: BRIEF.client, preparedAt: new Date().toISOString(), summary: 'Four platform-specific simulation connectors executed through AURA. Seller inventory is the first priority; three ad tests and all copy remain proposals.', simulated: true, sourceRunId: run.id, sourceRunStatus: run.status, brief: BRIEF, periods: PERIODS, sources, activity, tests: ['google','meta','amazon'].map(key => ({ source: key, ...sources[key].test })), websitePurchases: null };
}
export function validateCommerceDelivery(data) {
  must(data?.kind === 'commerce_tools' && data.simulated === true && data.sourceRunId && COMMERCE_ORDER.every(key => data.sources?.[key]?.receipt?.mode === 'server_simulated_tool_adapter') && data.activity?.length === 4, 'This review requires all four actual simulated-tool receipts.');
  return data;
}
