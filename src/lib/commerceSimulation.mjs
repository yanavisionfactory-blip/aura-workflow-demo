// Isolated authored scenario. No vendor client, account or backend is imported.
export const TOOLS = { seller: 'Amazon Seller Central', google: 'Google Ads', meta: 'Meta Ads Manager', amazon: 'Amazon Ads' };
export const PERIODS = { previous: '2026-10-05 / 2026-10-11', current: '2026-10-12 / 2026-10-18' };
export const BRIEF = {
  client: 'Harbor & Field — fictional Unstoprev client scenario',
  product: 'Everyday Travel Mug', asin: 'B0SIMMUG16', asinNotice: 'Fabricated scenario identifier; no Amazon listing is linked or verified.',
  website: 'https://harborandfield.example/products/everyday-travel-mug',
  facts: ['16 oz capacity', 'Stainless steel', 'Reusable cup with fitted lid', 'Hand-wash mug and lid'],
  offer: 'Website: illustrative 10% off with MUG10, October 19–November 1, 2026. Amazon: no offer assumed. The shared message omits the website-only offer.',
  targets: { googleCpa: 25, metaCpa: 30, amazonAcos: .25, minimumStockDays: 14 },
  timezone: 'America/Chicago', currency: 'USD', cutoff: '2026-10-22T06:00:00Z',
  approval: 'Authored scenario facts and targets only. Real client engagement, claims, offers, accounts and approvals are unverified.',
};
const definitions = {
  google: { attribution: 'SIMULATED: 30-day click, data-driven purchase credits', dateBasis: 'Ad interaction date', clicks: 'Ad clicks', conversions: 'Google-attributed website purchase credits', sales: 'Google-attributed website purchase value; not all website sales', caution: 'The 30-day window is open for both weeks. Values may restate.' },
  meta: { attribution: 'SIMULATED: 7-day click / 1-day view', dateBasis: 'Ad impression date', clicks: 'Link clicks', conversions: 'Meta-attributed website purchases', sales: 'Meta-attributed website purchase value; not all website sales', caution: 'Latest-week attribution is still open at the cutoff. View-through overlap is not deduplicated.' },
  amazon: { attribution: 'SIMULATED: Sponsored Products, seller, 7-day click, advertised-ASIN sales only', dateBasis: 'Ad click date', clicks: 'Sponsored Products clicks', conversions: 'Attributed advertised-ASIN orders', sales: 'Amazon Ads attributed advertised-ASIN sales', caution: 'The latest week is provisional. Validate actual report/product attribution settings before real use.' },
  seller: { attribution: 'Not ad-attributed: total ASIN business-report sales', dateBasis: 'Order date; current inventory is a separate point-in-time snapshot', clicks: 'Not applicable; sessions are product-detail traffic', conversions: 'Unit session percentage = units ordered / sessions', sales: 'Total ordered product sales for this ASIN', caution: 'Unit session percentage is units per session, not unique-buyer conversion. Do not add sales to Amazon Ads.' },
};
const ad = (id, period, campaign, entity, impressions, clicks, spend, purchases, sales, report = 'performance') => ({ id, period, campaign, entity, impressions, clicks, spend, purchases, sales, report });
export function simulationInputs(stock = 'low') {
  if (!['low', 'ready'].includes(stock)) throw new Error('Choose a supported simulated stock scenario.');
  return structuredClone({
    seller: { key: 'seller', simulated: true, periods: PERIODS, currency: BRIEF.currency, timezone: BRIEF.timezone, cutoff: BRIEF.cutoff, definitions: definitions.seller, rows: [
      { id: 'S-P', period: 'previous', asin: BRIEF.asin, sessions: 4500, units: 315, sales: 10080, featuredOffer: .94 },
      { id: 'S-C', period: 'current', asin: BRIEF.asin, sessions: 5000, units: 300, sales: 9600, featuredOffer: .79 },
    ], listing: { id: 'S-STOCK', asin: BRIEF.asin, title: 'Everyday Stainless Steel Travel Mug 16oz Coffee Cup', bullets: ['Great for drinks', 'Made for every day', 'Easy care'], status: 'active', suppressed: false, available: stock === 'low' ? 30 : 900, reserved: 10, inboundNotReceived: 200, snapshot: BRIEF.cutoff, issues: ['Care instructions absent from current bullets', 'Fitted-lid detail image absent'] } },
    google: { key: 'google', simulated: true, periods: PERIODS, currency: BRIEF.currency, timezone: BRIEF.timezone, cutoff: BRIEF.cutoff, definitions: definitions.google, rows: [
      ad('G-P-B', 'previous', 'SIM Brand Search', 'Brand ad', 10000, 1000, 500, 50, 1600), ad('G-C-B', 'current', 'SIM Brand Search', 'Brand ad', 11000, 990, 594, 45, 1440),
      ad('G-P-N', 'previous', 'SIM Nonbrand Search', 'Routine message', 50000, 2000, 2000, 80, 2560), { ...ad('G-C-N', 'current', 'SIM Nonbrand Search', 'Routine message', 52000, 2080, 2704, 65, 2080), headline: 'Make It Part of Your Routine' },
      ad('G-Q-P-1', 'previous', 'SIM Nonbrand Search', 'coffee mug', 25000, 1000, 1200, 24, 768, 'search_terms'), ad('G-Q-C-1', 'current', 'SIM Nonbrand Search', 'coffee mug', 35000, 1350, 2025, 18, 576, 'search_terms'),
      ad('G-Q-P-2', 'previous', 'SIM Nonbrand Search', '16 oz travel mug', 15000, 600, 500, 35, 1120, 'search_terms'), ad('G-Q-C-2', 'current', 'SIM Nonbrand Search', '16 oz travel mug', 12000, 500, 450, 32, 1024, 'search_terms'),
      ad('G-Q-P-3', 'previous', 'SIM Nonbrand Search', 'other reported terms', 10000, 400, 300, 21, 672, 'search_terms'), ad('G-Q-C-3', 'current', 'SIM Nonbrand Search', 'other reported terms', 5000, 230, 229, 15, 480, 'search_terms'),
    ] },
    meta: { key: 'meta', simulated: true, periods: PERIODS, currency: BRIEF.currency, timezone: BRIEF.timezone, cutoff: BRIEF.cutoff, definitions: definitions.meta, rows: [
      ad('M-P-STATIC', 'previous', 'SIM Mug Prospecting', 'Static lifestyle', 80000, 960, 1200, 40, 1280), ad('M-C-STATIC', 'current', 'SIM Mug Prospecting', 'Static lifestyle', 100000, 900, 1700, 34, 1088),
      ad('M-P-VIDEO', 'previous', 'SIM Mug Prospecting', 'Product demonstration', 40000, 640, 800, 40, 1280), ad('M-C-VIDEO', 'current', 'SIM Mug Prospecting', 'Product demonstration', 50000, 800, 800, 40, 1280),
    ] },
    amazon: { key: 'amazon', simulated: true, periods: PERIODS, currency: BRIEF.currency, timezone: BRIEF.timezone, cutoff: BRIEF.cutoff, definitions: definitions.amazon, rows: [
      ad('A-P-AUTO', 'previous', 'SIM SP Mug Auto', BRIEF.asin, 60000, 900, 900, 110, 3520), ad('A-C-AUTO', 'current', 'SIM SP Mug Auto', BRIEF.asin, 66000, 1000, 1100, 100, 3200),
      ad('A-P-MAN', 'previous', 'SIM SP Mug Manual', BRIEF.asin, 40000, 500, 600, 100, 3200), ad('A-C-MAN', 'current', 'SIM SP Mug Manual', BRIEF.asin, 42000, 520, 650, 110, 3520),
      ad('A-Q-P-1', 'previous', 'SIM SP Mug Auto', '16 oz stainless steel travel mug', 20000, 250, 280, 50, 1600, 'search_terms'), ad('A-Q-C-1', 'current', 'SIM SP Mug Auto', '16 oz stainless steel travel mug', 22000, 300, 330, 60, 1920, 'search_terms'),
      ad('A-Q-P-2', 'previous', 'SIM SP Mug Auto', 'large ceramic coffee mug', 20000, 400, 400, 25, 800, 'search_terms'), ad('A-Q-C-2', 'current', 'SIM SP Mug Auto', 'large ceramic coffee mug', 24000, 500, 550, 20, 640, 'search_terms'),
      ad('A-Q-P-3', 'previous', 'SIM SP Mug Auto', 'other reported terms', 20000, 250, 220, 35, 1120, 'search_terms'), ad('A-Q-C-3', 'current', 'SIM SP Mug Auto', 'other reported terms', 20000, 200, 220, 20, 640, 'search_terms'),
    ] },
  });
}
export const ratio = (a, b) => b ? a / b : null;
export const movement = (a, b) => b ? (a - b) / b : null;
const must = (condition, message) => { if (!condition) throw new Error(message); };
const sum = (rows, key) => rows.reduce((total, row) => total + row[key], 0);
const digest = async value => [...new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(value))))].map(v => v.toString(16).padStart(2, '0')).join('');

export async function executeTool(input) {
  must(input?.simulated === true && Object.hasOwn(TOOLS, input.key), 'Only isolated simulated tool inputs are accepted.');
  must(input.currency === BRIEF.currency && input.timezone === BRIEF.timezone && input.cutoff === BRIEF.cutoff && JSON.stringify(input.periods) === JSON.stringify(PERIODS), 'Reporting periods, currency, timezone and cutoff must align.');
  must(JSON.stringify(input.definitions) === JSON.stringify(definitions[input.key]), 'Keep the scenario attribution definitions intact.');
  const ids = new Set();
  for (const row of input.rows) {
    must(row.id && !ids.has(row.id) && ['previous', 'current'].includes(row.period), 'Evidence IDs and periods must be valid and unique.'); ids.add(row.id);
    const metrics = input.key === 'seller' ? ['sessions', 'units', 'sales', 'featuredOffer'] : ['impressions', 'clicks', 'spend', 'purchases', 'sales'];
    must(metrics.every(key => Number.isFinite(row[key]) && row[key] >= 0), 'Invalid or missing numeric source metric.');
    if (input.key === 'seller') must(row.asin === BRIEF.asin && row.featuredOffer <= 1, 'Seller ASIN or Featured Offer share is invalid.');
    else must(['performance', 'search_terms'].includes(row.report) && row.clicks <= row.impressions, 'Invalid ad report grain or denominator.');
  }
  const comparison = {};
  for (const period of ['previous', 'current']) {
    const rows = input.rows.filter(row => row.period === period && (input.key === 'seller' || row.report === 'performance'));
    must(rows.length > 0, 'Both complete weeks need non-overlapping primary rows.');
    const fields = input.key === 'seller' ? ['sessions', 'units', 'sales'] : ['impressions', 'clicks', 'spend', 'purchases', 'sales'];
    const totals = Object.fromEntries(fields.map(key => [key, sum(rows, key)]));
    comparison[period] = input.key === 'seller' ? { ...totals, unitSessionRate: ratio(totals.units, totals.sessions), featuredOffer: ratio(sum(rows.map(row => ({ value: row.featuredOffer * row.sessions })), 'value'), totals.sessions) } : { ...totals, cpa: ratio(totals.spend, totals.purchases), ctr: ratio(totals.clicks, totals.impressions), acos: ratio(totals.spend, totals.sales) };
  }
  if (['google', 'amazon'].includes(input.key)) {
    for (const period of ['previous', 'current']) {
      const queryRows = input.rows.filter(row => row.period === period && row.report === 'search_terms');
      must(queryRows.length > 0, 'Search-term evidence is required.');
      for (const campaign of new Set(queryRows.map(row => row.campaign))) {
        const primary = input.rows.filter(row => row.period === period && row.report === 'performance' && row.campaign === campaign);
        for (const field of ['impressions', 'clicks', 'spend', 'purchases', 'sales']) must(Math.abs(sum(queryRows.filter(row => row.campaign === campaign), field) - sum(primary, field)) < .00001, 'Search-term breakdown must reconcile without double counting.');
      }
    }
  }
  let readiness = null;
  if (input.key === 'seller') {
    const listing = input.listing;
    must(listing && listing.asin === BRIEF.asin && listing.snapshot === BRIEF.cutoff && ['available', 'reserved', 'inboundNotReceived'].every(key => Number.isInteger(listing[key]) && listing[key] >= 0), 'A dated, matching listing and available-stock snapshot is required.');
    const cover = ratio(listing.available, comparison.current.units / 7);
    readiness = { daysCover: cover, promotionReady: listing.status === 'active' && listing.suppressed === false && cover !== null && cover >= BRIEF.targets.minimumStockDays, evidence: ['S-C', 'S-STOCK'], note: 'Cover is an illustrative available-units / latest-week daily-units estimate. Reserved and unreceived inbound are excluded; website inventory is unconfirmed.' };
  }
  return { ...structuredClone(input), comparison, readiness, receipt: { id: globalThis.crypto.randomUUID(), operation: `${input.key}.simulated.review`, executed_at: new Date().toISOString(), input_sha256: await digest(input), executor: 'AURA browser simulation adapter', provider_api_called: false, external_writes: false } };
}

function proposals(sources) {
  const hold = sources.seller.readiness.promotionReady ? 'Scenario stock gate passed; account-manager approval remains required.' : 'HOLD additional Amazon promotion until available stock is verified above the 14-day scenario minimum.';
  const common = 'Proposed only. Confirm power, assignment units, minimum sample, practical effect, analysis method and stopping rule before setup. Run at least two full weeks and wait for the source conversion window plus reporting lag; the weekly comparison proves no cause or significance.';
  const tests = [
    { id: 'T-G', source: 'google', campaign: 'SIM Nonbrand Search', title: 'Capacity-first Search message', evidence: ['G-C-N', 'G-Q-C-1', 'G-Q-C-2'], observation: 'Broad “coffee mug” costs $112.50 per purchase credit; “16 oz travel mug” costs $14.06. Query mix may explain part of the aggregate change; this is descriptive.', change: 'Within the existing 16 oz intent segment, compare the current scenario message “Make It Part of Your Routine” with “A 16 oz Mug for Your Routine”. Change only the lead headline; hold queries, bidding, audience, landing page and total budget fixed.', learning: 'Does stating capacity first improve Google purchase-credit CPA toward $25?', design: `Use a mutually exclusive 50/50 campaign experiment; verify responsive-ad asset eligibility and pinning before isolating the lead headline. ${common}`, primary: 'Google purchase-credit CPA; guardrails: purchase-credit rate, attributed value/cost and traffic balance.', approval: 'Account manager: copy, facts, purchase conversion, split, sample plan, destination and unchanged-budget setup. Website stock pool needs confirmation.' },
    { id: 'T-M', source: 'meta', campaign: 'SIM Mug Prospecting', title: 'Product demonstration versus lifestyle static', evidence: ['M-C-STATIC', 'M-C-VIDEO'], observation: 'Static creative has $50 CPA versus $20 for the product demonstration. Audience and delivery mix can confound this comparison.', change: 'Use a platform randomized A/B test of the two creative concepts. Keep primary text, headline, audience, placements, optimization event and total budget fixed.', learning: 'Does showing capacity, stainless steel and the fitted lid improve Meta purchase CPA toward $30?', design: `50/50 mutually exclusive eligible audiences; concept is the treatment, not a claim about an isolated video element. ${common}`, primary: 'Meta purchase CPA; guardrails: link CTR, landing-page purchases, frequency and creative policy.', approval: 'Account manager: two assets, factual claims, rights, tracking, placements and sample plan. Website stock pool needs confirmation.' },
    { id: 'T-A', source: 'amazon', campaign: `SIM SP Mug Auto / ${BRIEF.asin}`, title: 'Exact targeting for the relevant query', evidence: ['A-Q-C-1', 'A-Q-C-2', 'A-C-AUTO', 'S-STOCK'], observation: 'Relevant 16 oz steel query has 17.19% ACoS; ceramic query has 85.94%. Auto campaign ACoS is 34.38%.', change: 'Propose an exact-keyword target for “16 oz stainless steel travel mug” in the manual campaign. After stock approval, define matched baseline and isolation/negative-exact routing to avoid duplicate query exposure; keep ASIN, listing, placement and total budget fixed.', learning: 'Can exact query control keep advertised-ASIN ACoS below 25% while retaining attributed orders?', design: `Use a pre-registered matched-period targeting pilot with an unchanged comparable control; it is directional, not randomized causal evidence. Do not edit the listing during this targeting test. ${common}`, primary: 'Advertised-ASIN ACoS and attributed orders; guardrails: total ASIN units, available stock and Featured Offer share.', approval: `Account manager: targeting, bid cap, isolation, sample plan and stock clearance. ${hold}` },
  ];
  const copy = { message: 'A reusable 16 oz stainless steel mug for your everyday routine.', google: { headlines: ['Meet Your Everyday Travel Mug', 'A 16 oz Mug for Your Routine'], description: 'Bring a reusable 16 oz stainless steel mug to your daily routine. Explore Harbor & Field.' }, meta: { primary: ['Your daily routine, with a mug you can reuse. Meet the Harbor & Field Everyday Travel Mug: 16 oz, stainless steel and a fitted lid.', 'From your morning coffee to your afternoon tea: explore a reusable 16 oz stainless steel mug with a fitted lid. Meet Harbor & Field.'], headline: 'Meet Your Everyday Travel Mug', brief: '15-second vertical and square product demonstration. Open on the mug beside a 16 oz capacity label; show steel body and fitted lid; finish with the mug in a daily coffee routine. Use the same framing and approved product imagery. Overlay “16 oz. Reusable. Everyday.” Use captions, high contrast and product-only visuals. Do not imply leak-proofing, thermal duration, dishwasher safety or unapproved health/environmental benefits. Keep both primary-text options as separate review variants; hold one fixed in the creative experiment.' }, seller: { title: 'Harbor & Field Everyday Travel Mug, 16 oz Stainless Steel Reusable Cup with Fitted Lid', bullets: ['EVERYDAY CAPACITY: A 16 oz travel mug for your morning coffee or afternoon tea.', 'REUSABLE STAINLESS STEEL: Bring the same mug into your everyday routine at home or on the go.', 'FITTED LID & CARE: Includes a fitted lid. Hand-wash the mug and lid; review the care guide before use.'] } };
  const checklist = [
    { id: 'P1', priority: 'P0', source: 'seller', target: BRIEF.asin, evidence: ['S-C', 'S-STOCK'], change: 'Review available stock, inbound receipt timing and Featured Offer eligibility before more promotion. Do not count unreceived inbound as available. No inventory change is included.', learning: 'Can the ASIN support promotion without stockout or lost Featured Offer exposure?', approval: `Marketplace owner and account manager: inventory/listing clearance. ${hold}` },
    { id: 'P2', priority: 'P1', source: 'seller', target: BRIEF.asin, evidence: ['S-P', 'S-C', 'S-STOCK'], change: 'Review the proposed title, three bullets and a fitted-lid detail image. Investigate the 94% to 79% Featured Offer decline and 7% to 6% unit-session rate. Keep listing changes separate from the targeting test.', learning: 'Can clearer product facts address missing information? Weekly rates do not establish the cause.', approval: 'Account manager: category title/bullet rules, factual claims, image rights and an independent listing-test plan.' },
    ...tests.map((test, i) => ({ id: `P${i + 3}`, priority: 'P2', source: test.source, target: test.campaign, evidence: test.evidence, change: test.change, learning: test.learning, approval: test.approval })),
    { id: 'P6', priority: 'P1', source: 'google', target: 'SIM website purchase tracking + all source definitions', evidence: ['G-P-N', 'G-C-N', 'M-C-STATIC', 'A-C-AUTO', 'S-C'], change: 'Re-extract mature attribution windows at a common cutoff; verify event deduplication and actual website orders from the store. Confirm separate or shared website/Amazon inventory pools. Do not sum platform purchase credits.', learning: 'Are outcomes comparable and tracking/stock ready for the proposed tests?', approval: 'Analytics owner and account manager: definitions, actual store report, stock mapping and test guardrails. Website total purchases are missing.' },
  ];
  return { tests, copy, checklist };
}

export async function executeCommerceSimulation(stock = 'low', onStep = () => {}) {
  const inputs = simulationInputs(stock), sources = {};
  // Listing/inventory check is deliberately the first executed operation.
  for (const key of ['seller', 'google', 'meta', 'amazon']) { sources[key] = await executeTool(inputs[key]); await onStep(key, sources[key]); }
  const packet = { version: 1, scenario: 'harbor_field_mug_v1', stock, simulated: true, brief: structuredClone(BRIEF), periods: structuredClone(PERIODS), sources, ...proposals(sources), websitePurchases: null, websitePurchasesNote: 'Unavailable: no independent store orders export. Ad-attributed website purchases are not total website purchases.', execution: { id: globalThis.crypto.randomUUID(), mode: 'browser_executed_simulation', source_operations: 4, completed_steps: 5, model_call_executed: false, provider_api_called: false, external_writes: false, drafting: 'Authored scenario proposals validated against the exact packaged fixture; no model generation or live provider call.' } };
  await validateCommercePacket(packet);
  return packet;
}

export async function validateCommercePacket(packet) {
  must(packet?.simulated === true && packet.scenario === 'harbor_field_mug_v1' && ['low', 'ready'].includes(packet.stock), 'Not an authorized scenario packet.');
  must(JSON.stringify(packet.brief) === JSON.stringify(BRIEF) && JSON.stringify(packet.periods) === JSON.stringify(PERIODS), 'Scenario brief or periods were altered.');
  must(packet.execution.mode === 'browser_executed_simulation' && packet.execution.source_operations === 4 && packet.execution.completed_steps === 5 && packet.execution.model_call_executed === false && packet.execution.provider_api_called === false && packet.execution.external_writes === false, 'Invalid execution provenance.');
  must(Object.keys(packet.sources).sort().join() === Object.keys(TOOLS).sort().join() && packet.websitePurchases === null, 'All four sources and separate website outcomes are required.');
  const expected = simulationInputs(packet.stock), evidence = new Set();
  for (const key of Object.keys(TOOLS)) {
    const source = packet.sources[key];
    const { comparison, readiness, receipt, ...original } = source;
    must(JSON.stringify(original) === JSON.stringify(expected[key]) && receipt.input_sha256 === await digest(original), 'Source fixture or hash was altered.');
    const recalculated = await executeTool(original);
    must(JSON.stringify(comparison) === JSON.stringify(recalculated.comparison) && JSON.stringify(readiness) === JSON.stringify(recalculated.readiness), 'Computed metrics or stock gate were altered.');
    must(receipt.id && !Number.isNaN(Date.parse(receipt.executed_at)) && receipt.executor === 'AURA browser simulation adapter' && receipt.operation === `${key}.simulated.review` && receipt.provider_api_called === false && receipt.external_writes === false, 'Missing source processing receipt.');
    source.rows.forEach(row => evidence.add(row.id)); if (source.listing) evidence.add(source.listing.id);
  }
  const authored = proposals(packet.sources);
  must(['tests', 'copy', 'checklist'].every(key => JSON.stringify(authored[key]) === JSON.stringify(packet[key])), 'Draft proposals must match their exact scenario evidence.');
  must(packet.tests.length === 3 && new Set(packet.tests.map(test => test.source)).size === 3, 'Three independent advertising tests are required.');
  for (const item of [...packet.tests, ...packet.checklist]) must(item.evidence.length && item.evidence.every(id => evidence.has(id)) && item.approval, 'Every proposal needs resolvable evidence and approval.');
  must(packet.copy.google.headlines.length === 2 && packet.copy.google.headlines.every(text => text.length <= 30) && packet.copy.google.description.length <= 90 && packet.copy.meta.primary.length === 2 && packet.copy.seller.bullets.length === 3, 'Copy fields or character limits are invalid.');
  return true;
}

export function commerceMarkdown(packet) {
  const lines = ['# SIMULATED — weekly marketing action package', '', packet.brief.client, `${PERIODS.current} versus ${PERIODS.previous} · ${BRIEF.timezone} · ${BRIEF.currency} · cutoff ${BRIEF.cutoff}`, '', '**Draft for account-manager review. All accounts, product facts, offers, targets and metrics are authored scenario data.**', 'Four AURA browser simulation adapters executed. Vendor APIs and model were not called. No campaigns, copy, budgets or inventory were changed.', '', '## Performance summary', '', '| Source | Spend previous → current | Outcomes previous → current | Sales previous → current | CPA or ACoS previous → current |', '|---|---:|---:|---:|---:|'];
  if (packet.reviewEdited) lines.splice(6, 0, '**Local review edits:** Copy includes manual changes made in this browser. Facts and claims need account-manager approval. Source reports and computed metrics are unchanged.');
  for (const [key, source] of Object.entries(packet.sources)) { const p = source.comparison.previous, c = source.comparison.current; lines.push(`| ${TOOLS[key]} | ${key === 'seller' ? 'Not applicable' : `${p.spend} → ${c.spend}`} | ${key === 'seller' ? `${p.units} → ${c.units} units` : `${p.purchases} → ${c.purchases} attributed credits/orders`} | ${p.sales} → ${c.sales} ${key === 'seller' ? 'total ASIN sales' : 'platform attributed sales'} | ${key === 'seller' ? `${100 * p.unitSessionRate}% → ${100 * c.unitSessionRate}% unit session rate` : key === 'amazon' ? `${(100 * p.acos).toFixed(2)}% → ${(100 * c.acos).toFixed(2)}% ACoS` : `${p.cpa.toFixed(2)} → ${c.cpa.toFixed(2)} CPA`} |`); }
  lines.push('', packet.websitePurchasesNote, 'Do not add website purchase credits, Amazon total sales or platform-attributed sales across sources.', '', '## Seller readiness', `Available stock: ${packet.sources.seller.listing.available}; estimated cover: ${packet.sources.seller.readiness.daysCover.toFixed(1)} days. Promotion gate: ${packet.sources.seller.readiness.promotionReady ? 'scenario stock ready; approval pending' : 'HOLD additional Amazon promotion'}.`, packet.sources.seller.readiness.note, '', '## Three proposed advertising tests');
  for (const test of packet.tests) lines.push('', `### ${test.id} — ${test.title}`, `${TOOLS[test.source]} · ${test.campaign}`, test.observation, test.change, test.design, `Learning: ${test.learning}`, `Measure: ${test.primary}`, `Approval: ${test.approval}`, `Evidence: ${test.evidence.map(id => `[${id}](#${id.toLowerCase()})`).join(', ')}`);
  lines.push('', '## Consistent product-message test', packet.copy.message, '', '### Google Ads', ...packet.copy.google.headlines.map(text => `- ${text}`), packet.copy.google.description, '', '### Meta Ads', ...packet.copy.meta.primary.map(text => `- ${text}`), `Headline: ${packet.copy.meta.headline}`, `Creative brief: ${packet.copy.meta.brief}`, '', '### Amazon Seller Central', packet.copy.seller.title, ...packet.copy.seller.bullets.map(text => `- ${text}`), '', '## Prioritized implementation checklist');
  for (const item of [...packet.checklist].sort((a, b) => a.priority.localeCompare(b.priority))) lines.push('', `### ${item.id} · ${item.priority} · ${TOOLS[item.source]} · ${item.target}`, item.change, `Expected learning: ${item.learning}`, `Approval required: ${item.approval}`, `Evidence: ${item.evidence.map(id => `[${id}](#${id.toLowerCase()})`).join(', ')}`);
  lines.push('', '## Product inputs', ...BRIEF.facts.map(text => `- SIMULATED fact: ${text}`), BRIEF.offer, `Website placeholder: ${BRIEF.website}`, `ASIN: ${BRIEF.asin} — ${BRIEF.asinNotice}`, BRIEF.approval, '', '## Source reports and evidence');
  for (const [key, source] of Object.entries(packet.sources)) { lines.push('', `### ${TOOLS[key]} · SIMULATED`, JSON.stringify(source.definitions), `Receipt: ${source.receipt.id}; SHA-256: ${source.receipt.input_sha256}; executed ${source.receipt.executed_at}`, 'Search terms are breakdowns and excluded from primary totals.'); for (const row of [...source.rows, ...(source.listing ? [source.listing] : [])]) lines.push('', `<a id="${row.id.toLowerCase()}"></a>`, `**${row.id}**`, JSON.stringify(row)); }
  return lines.join('\n');
}
