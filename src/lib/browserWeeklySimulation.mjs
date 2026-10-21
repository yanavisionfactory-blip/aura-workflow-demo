import { allPlatformSimulationRequest, WEEKLY_PLATFORMS } from './weeklyReviewIntake.mjs';
import { totals, change, percent, validatePacket } from './weeklyAccountReview.mjs';

export const BROWSER_WEEKLY_KEY = 'aura.seven-platform-browser-simulation.v1';
export const BROWSER_WEEKLY_MODE = 'browser_executed_simulation';
const requireValue = (condition, message) => { if (!condition) throw new Error(message); };
const refs = (key) => [`SIM-${key}-previous`, `SIM-${key}-current`];
const sha256 = async (text) => Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), value => value.toString(16).padStart(2, '0')).join('');

export function browserSimulationInputs(now = new Date()) {
  const request = allPlatformSimulationRequest(now);
  const encoded = request.resources.documents[0].file_url.split(',')[1];
  return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(encoded), char => char.charCodeAt(0))));
}

export function parseSimulationSource(input, config) {
  const platform = WEEKLY_PLATFORMS.find(item => item.key === input.source_key);
  requireValue(platform && input.input_kind === 'simulated_scenario' && input.metadata?.simulationOnly === true && input.metadata?.simulationAuthorized === true && input.metadata?.provenance === 'simulated', 'Browser simulation accepts explicitly labelled sample inputs only.');
  requireValue(['currency', 'timezone', 'asOf'].every(key => input.metadata[key] === config[key]) && JSON.stringify(input.periods) === JSON.stringify(config.periods), `${platform.name}: reporting periods or definitions do not align.`);
  requireValue(['attribution', 'dateBasis', 'clickDefinition', 'conversionDefinition', 'revenueDefinition'].every(key => input.metadata[key]?.trim()), `${platform.name}: metric definitions are required.`);
  const metrics = platform.kind === 'paid' ? ['impressions', 'clicks', 'spend', 'conversions', 'revenue'] : ['delivered', 'uniqueClicks', 'conversions', 'revenue', 'unsubscribes'];
  const expected = ['provenance', 'source', 'id', 'period', 'campaign', ...metrics];
  // This route processes only AURA's authored, unquoted sample format. Client CSV
  // uploads continue through the approved-export backend route.
  const lines = input.csv_text.trim().split(/\r?\n/).map(line => line.split(','));
  requireValue(JSON.stringify(lines[0]) === JSON.stringify(expected) && lines.length === 3, `${platform.name}: unexpected sample CSV schema.`);
  const rows = lines.slice(1).map((cells, i) => {
    const period = i === 0 ? 'previous' : 'current';
    requireValue(cells.length === expected.length && cells[0] === 'SIMULATED' && cells[1] === platform.name && cells[2] === refs(platform.key)[i] && cells[3] === period && cells[4].startsWith('SIMULATED '), `${platform.name}: source identity or simulation label is invalid.`);
    const row = { id: cells[2], period, campaign: cells[4] };
    metrics.forEach((metric, index) => {
      requireValue(cells[index + 5].trim() !== '' && Number.isFinite(Number(cells[index + 5])) && Number(cells[index + 5]) >= 0, `${platform.name}: invalid ${metric}.`);
      row[metric === 'conversions' ? 'purchases' : metric] = Number(cells[index + 5]);
    });
    requireValue(platform.kind === 'paid' ? row.clicks <= row.impressions : row.uniqueClicks <= row.delivered && row.unsubscribes <= row.delivered, `${platform.name}: invalid metric denominator.`);
    return row;
  });
  return { ...input.metadata, key: platform.key, name: platform.name, kind: platform.kind, accountId: `SIM-${platform.key.toUpperCase()}`, provenance: 'simulated', rows, inputCsv: input.csv_text };
}

export function simulationFindings(sources, threshold) {
  return sources.flatMap(source => {
    const previous = totals(source, 'previous'), current = totals(source, 'current');
    const metrics = source.kind === 'paid' ? ['spend', 'purchases', 'cpa', 'roas', 'ctr'] : ['uniqueClicks', 'clickRate', 'revenuePerDelivery', 'unsubscribes'];
    return metrics.map(metric => {
      const movement = change(current[metric], previous[metric]);
      return { id: `F-${source.key}-${metric}`, source: source.key, metric, previous: previous[metric], current: current[metric], change: movement, material: movement !== null && Math.abs(movement) + 1e-12 >= threshold, provenance: 'simulated', baselineStatus: previous[metric] === 0 ? 'no_comparable_baseline' : 'comparable', evidence: refs(source.key) };
    });
  });
}

function draftProposals(sources) {
  const pair = key => [totals(sources.find(source => source.key === key), 'previous'), totals(sources.find(source => source.key === key), 'current')];
  const [gp, gc] = pair('google'), [mp, mc] = pair('meta'), [kp, kc] = pair('klaviyo');
  const experiments = [
    { id: 'E1', source: 'google', title: 'Test a furniture-discovery headline theme', evidence: refs('google'), status: 'proposed', simulationBased: true,
      hypothesis: `SIMULATED Google purchase-credit CPA rose from $${gp.cpa.toFixed(2)} to $${gc.cpa.toFixed(2)}. A clearer sofa/sectional discovery theme may improve qualified response; the weekly movement does not identify the cause.`,
      change: 'Compare the proposed baseline headline theme with a room-focused theme. No observed live control copy was supplied.',
      design: 'Propose a 50/50 platform experiment with mutually exclusive eligible traffic. Hold audience, keywords, exclusions, landing page, bidding and total budget fixed; change only the headline theme. Validate placement eligibility first.',
      primary: 'Google purchase-credit CPA = Google spend / Google attributed purchase credits; scenario definition: 30-day click, data-driven credits. Do not blend with other platforms.',
      guardrails: 'Monitor source-specific ROAS, conversion rate, policy eligibility and traffic balance. No automatic budget or campaign action.',
      decision: 'Before launch, register a 10% CPA improvement target, analysis method and stopping rule. Choose a winner only when the mature effect meets the target and its 95% confidence interval excludes no improvement; otherwise retain an inconclusive result.',
      feasibility: 'Use actual conversion variance and volume for an 80% power calculation before selecting duration. Run at least two full weeks, use a predeclared maximum duration, and wait the full 30-day click window plus validated reporting lag. These aggregate sample rows cannot establish power.',
      owner: 'Paid search analyst (proposed)', effort: '3 hours setup + monitoring after approval', dependencies: ['B1', 'B2', 'B3'], creative: 'C1' },
    { id: 'E2', source: 'meta', title: 'Test the opening furniture-discovery hook', evidence: refs('meta'), status: 'proposed', simulationBased: true,
      hypothesis: `SIMULATED Meta link CTR fell from ${percent(mp.ctr)} to ${percent(mc.ctr)} and CPA rose from $${mp.cpa.toFixed(2)} to $${mc.cpa.toFixed(2)}. An alternative opening hook may improve response; fatigue, audience and auction causes remain unverified.`,
      change: 'Change only the first-line hook between the two proposed variants; keep image, body, headline, CTA and landing page fixed.',
      design: 'Use a platform split test with non-overlapping audiences and a 50/50 split. Hold objective, placement, schedule, audience, bid settings and total budget constant. Neither variant is a claimed existing control.',
      primary: 'Meta paid-link CTR = paid link clicks / impressions. Secondary: Meta-only attributed purchase CPA, with the scenario 7-day click / 1-day view window.',
      guardrails: 'Require source-specific CPA and ROAS to remain within predeclared acceptable bounds; monitor frequency, negative feedback and balance. Reach/frequency were not supplied, so assess them before launch.',
      decision: 'Register a 15% relative link-CTR improvement target and 95% interval rule before launch. Advance only if CTR meets the target and downstream CPA/ROAS guardrails hold after maturity; otherwise inconclusive or reject.',
      feasibility: 'Plan 80% power using actual baseline CTR and experiment assignment units. Run at least two full weeks with a predeclared maximum, then allow seven days plus reporting lag for click conversions. No significance is inferred from these weekly totals.',
      owner: 'Paid social analyst (proposed)', effort: '2 hours creative setup + review', dependencies: ['B1', 'B2', 'B3'], creative: 'C2' },
    { id: 'E3', source: 'klaviyo', title: 'Test a welcome-email subject line', evidence: refs('klaviyo'), status: 'proposed', simulationBased: true,
      hypothesis: `SIMULATED Klaviyo welcome-email click rate fell from ${percent(kp.clickRate)} to ${percent(kc.clickRate)}. A different subject may improve clicks, but the aggregate rows do not isolate subject effects from cohort composition.`,
      change: 'Compare a category-discovery subject with a room-focused subject. Keep preheader, body, CTA and destination identical.',
      design: 'Randomize eligible opted-in recipients once within the same welcome-message position, segment and send-time block. Use a 50/50 split and suppress crossover. Validate actual eligibility, consent and suppression rules before implementation.',
      primary: 'Per-message unique clicked deliveries / delivered emails; bots excluded. Opens are excluded. Klaviyo-only attributed value uses the scenario 5-day email-click window.',
      guardrails: 'Monitor unsubscribe, complaint and delivery rates per delivered message. Sample unsubscribe rate doubled from 0.1% to 0.2%; investigate eligibility before sending. No message is sent by this workflow.',
      decision: 'Register a 15% relative click-rate improvement target and 95% interval rule; require unsubscribe and complaint guardrails to hold. Use intent-to-treat reporting with delivery rates shown, and report inconclusive if the powered sample is not reached.',
      feasibility: 'Use actual recipient-level baseline rates for 80% power planning and predefine the sample and maximum enrollment duration. Keep cohorts comparable and wait five days plus reporting lag after the last message for attributed value.',
      owner: 'Lifecycle marketer (proposed)', effort: '2 hours setup + consent and QA review', dependencies: ['B1', 'B2', 'B3', 'B5'], creative: 'C3' },
  ];
  const blank = { headlines: [], descriptions: [], hook: '', visual: '', text: '', headline: '', cta: '', subject: '' };
  const email = { preheader: '', greeting: '', body: '', cta: '' };
  const descriptions = ['Explore sofas and sectionals for your living room.', 'Browse living-room furniture and find a style to explore.'];
  const metaFixed = { visual: 'Proposed approved catalog image of a sofa in a living room; identical in both variants.', text: 'Explore sofas and sectionals for your living room.', headline: 'Explore Living-Room Furniture', cta: 'Learn more' };
  const creatives = [
    { id: 'C1', source: 'google', experiment: 'E1', title: 'Google Search headline-theme pair', simulationBased: true, destination: 'Approved catalog destination required before launch', note: 'Scenario copy; A is a proposed baseline, not observed live copy. Descriptions and destination stay fixed.', shared: { ...email }, variants: [
      { ...blank, label: 'A · proposed baseline', headlines: ['Explore Living Room Furniture', 'Sofas And Sectionals', 'Find Your Next Sofa'], descriptions },
      { ...blank, label: 'B · room-focused theme', headlines: ['Find A Sofa For Your Room', 'Explore Your Living Room Style', 'Discover Sofas And Sectionals'], descriptions },
    ] },
    { id: 'C2', source: 'meta', experiment: 'E2', title: 'Meta opening-hook pair', simulationBased: true, destination: 'Approved catalog destination required before launch', note: 'Only the opening hook changes. Use approved imagery; no price, discount, shipping or performance claims.', shared: { ...email }, variants: [
      { ...blank, ...metaFixed, label: 'A · proposed baseline', hook: 'Looking for your next sofa?' },
      { ...blank, ...metaFixed, label: 'B · room-focused hook', hook: 'What will your living room look like next?' },
    ] },
    { id: 'C3', source: 'klaviyo', experiment: 'E3', title: 'Klaviyo welcome-email subject pair', simulationBased: true, destination: 'Approved catalog destination required before sending', note: 'Subject-only test; all shared fields, audience and send-time rules stay fixed. Add approved footer, preferences and unsubscribe link during implementation QA.', shared: { preheader: 'Explore sofas, sectionals and living-room furniture.', greeting: 'Hello,', body: 'Welcome. Explore sofas and sectionals, and find living-room furniture that fits the style you have in mind. Take a look through the collection to start your search.', cta: 'Explore living-room furniture' }, variants: [
      { ...blank, label: 'A · proposed baseline', subject: 'Explore sofas and sectionals' },
      { ...blank, label: 'B · room-focused subject', subject: 'What’s next for your living room?' },
    ] },
  ];
  const task = (id, priority, source, title, fix, reasoning, acceptance, dependencies, owner, effort) => ({ id, priority, source, title, fix, reasoning, acceptance, dependencies, owner, effort, status: 'proposed', simulationBased: true, evidence: source === 'all' ? sources.flatMap(item => refs(item.key)) : refs(source) });
  const backlog = [
    task('B1', 'P1', 'all', 'Validate the real client scope and approved brief', 'Obtain actual client/account mapping, contracted platforms, goals, claims and brand approvals before implementing any scenario proposal.', 'All seven inputs and business assumptions are simulated.', 'Each actual source and claim has a named approval reference; remove platforms outside scope.', [], 'Account lead', '1–2 hours plus client review'),
    task('B2', 'P1', 'all', 'Reconcile definitions, dates and attribution maturity', 'Replace samples with approved comparable cohorts and mature exports; document deduplication limits, timezone, currency, cutoff and attribution per source.', 'The seven systems use different outcome windows and overlapping outcome credits.', 'Seven scoped source definitions pass validation; no blended attributed revenue or unique-order total; maturity and lag recorded.', ['B1'], 'Analytics lead', '3–4 hours'),
    task('B3', 'P1', 'all', 'Pre-register experiment design and approve copy', 'Approve the three proposals, baseline copy, destinations, power calculations, allocation, stopping rules and guardrail thresholds before setup.', 'Weekly materiality alone cannot establish a cause, statistical significance or adequate sample size.', 'Experiment owners sign off on powered samples, 95% intervals, duration and policy/brand QA; no launch action is included.', ['B1', 'B2'], 'Experiment lead', '4–6 hours'),
    task('B4', 'P2', 'amazon', 'Investigate Amazon efficiency decline', 'Review actual placements, product availability, search terms and attribution maturity before proposing a placement-specific test.', 'SIMULATED CPA rose from $15 to $20 and ROAS fell from 4× to 3×; aggregate rows do not identify a driver.', 'Validated breakdown explains the descriptive movement or records the diagnosis as unresolved; placement and eligible creative format documented.', ['B2'], 'Marketplace analyst', '2 hours'),
    task('B5', 'P1', 'klaviyo', 'Check welcome-cohort eligibility and suppression', 'Inspect actual consent, segment composition, suppression rules and delivery quality before testing subjects.', 'SIMULATED clicks per delivered email fell 30% and unsubscribe rate doubled; composition is not supplied.', 'Comparable eligible cohorts and unsubscribe/complaint thresholds approved; suppressions and tracking QA complete.', ['B1', 'B2'], 'Lifecycle marketer', '2–3 hours'),
    task('B6', 'P2', 'hubspot', 'Review nurture-journey cohorts', 'Compare the same nurture-message position and recipient eligibility; check tracking and suppression before recommending copy changes.', 'SIMULATED unique click rate fell from 3% to 2%, while the delivered cohort grew; this does not isolate a cause.', 'Cohort and message-position comparability documented; click and attributed-value definitions reconciled.', ['B2'], 'Marketing automation specialist', '2 hours'),
    task('B7', 'P2', 'microsoft', 'Validate improved Microsoft performance', 'Check mature attribution, campaign mix and conversion quality before extending any winning pattern.', 'SIMULATED CPA fell 20% and ROAS rose 25%; no scale or budget change is justified from a sample.', 'Improvement reproduced with approved comparable evidence and conversion-quality checks; no automatic scaling.', ['B2'], 'Paid search analyst', '1–2 hours'),
    task('B8', 'P2', 'mailchimp', 'Validate newsletter engagement improvement', 'Compare matched message/segment cohorts and delivery counts; retain email-only scope.', 'SIMULATED click rate rose from 3% to 4%; this does not show causal subject-line lift.', 'Actual cohort comparability, click filtering and subscription rules confirmed before reusing creative.', ['B2'], 'Email marketer', '1–2 hours'),
    task('B9', 'P1', 'all', 'Confirm the real reporting destination before handoff', 'Keep this simulation in AURA and local downloads. For a real engagement, confirm the named destination, account access and reviewer.', 'No selected real-client reporting destination has been verified.', 'Destination URL, account owner, access and approval reference documented before any external delivery; nothing sent by this run.', ['B1', 'B2'], 'Account lead', '30–60 minutes'),
  ];
  return { experiments, creatives, backlog };
}

export function validateBrowserSimulation(packet) {
  const errors = validatePacket(packet);
  if (!packet.simulationOnly || !packet.client.fictional || packet.client.engagementConfirmed || packet.scope.confirmed || packet.reporting.confirmed) errors.push('Simulation cannot claim real approvals.');
  if (packet.execution.mode !== BROWSER_WEEKLY_MODE || packet.execution.source_operations !== 7 || packet.execution.completed_steps !== 8 || packet.execution.provider_api_called !== false || packet.execution.model_call_executed !== false || packet.execution.external_writes !== false) errors.push('Browser execution provenance is invalid.');
  const keys = new Set(packet.sources.map(source => source.key));
  if (keys.size !== 7 || WEEKLY_PLATFORMS.some(source => !keys.has(source.key))) errors.push('Exactly seven unique simulated sources are required.');
  const taskIds = new Set(packet.backlog.map(item => item.id));
  const byId = new Map(packet.backlog.map(item => [item.id, item]));
  for (const item of [...packet.experiments, ...packet.backlog]) {
    if (item.dependencies.some(id => !taskIds.has(id))) errors.push(`Missing dependency: ${item.id}`);
    if (item.source !== 'all' && item.evidence.some(id => !packet.sources.find(source => source.key === item.source)?.rows.some(row => row.id === id))) errors.push(`Cross-source evidence: ${item.id}`);
  }
  const visit = (id, path) => { if (path.includes(id)) { errors.push('Cyclic dependency'); return; } for (const dep of byId.get(id)?.dependencies || []) visit(dep, [...path, id]); };
  for (const id of taskIds) visit(id, []);
  for (const creative of packet.creatives) {
    const experiment = packet.experiments.find(item => item.id === creative.experiment);
    if (!experiment || experiment.source !== creative.source || experiment.creative !== creative.id || creative.variants.length !== 2) errors.push('Creative links or variant counts are invalid.');
  }
  if (packet.creatives.length !== 3 || packet.backlog.length < 6 || packet.backlog.length > 10) errors.push('Incomplete simulation deliverables.');
  return errors;
}

export async function runBrowserWeeklySimulation({ now = new Date(), onStep = () => {}, inputs = browserSimulationInputs(now) } = {}) {
  const { config, sources: inputsBySource } = inputs;
  requireValue(config.simulationOnly === true && inputsBySource.length === 7 && config.client.fictional === true, 'Only the seven-platform simulation can run in this browser route.');
  const authored = browserSimulationInputs(new Date(config.asOf));
  requireValue(JSON.stringify(inputs) === JSON.stringify(authored), 'This browser route accepts the authored seven-platform sample only. Use the backend route for other exports.');
  const sources = [];
  for (const input of inputsBySource) {
    onStep({ key: input.source_key, status: 'running' });
    const source = parseSimulationSource(input, config);
    source.execution = { id: globalThis.crypto.randomUUID(), executor: 'AURA browser sample processor', executed_at: new Date().toISOString(), input_sha256: await sha256(input.csv_text), input_bytes: new TextEncoder().encode(input.csv_text).length, provider_api_called: false, synthetic: true };
    sources.push(source);
    onStep({ key: input.source_key, status: 'completed', receipt: source.execution });
  }
  onStep({ key: 'review', status: 'running' });
  const findings = simulationFindings(sources, config.materialityThreshold);
  const summary = ['SIMULATED training account — every number and business assumption is fictional. AURA parsed and hashed seven sample exports in this browser; no vendor reporting API or backend model was called.',
    ...sources.map(source => { const p = totals(source, 'previous'), c = totals(source, 'current'); return source.kind === 'paid' ? `${source.name} (SIMULATED): CPA $${p.cpa.toFixed(2)} → $${c.cpa.toFixed(2)} (${percent(change(c.cpa, p.cpa))}); source-specific ROAS ${p.roas.toFixed(2)}× → ${c.roas.toFixed(2)}× (${percent(change(c.roas, p.roas))}).` : `${source.name} (SIMULATED): unique clicked deliveries / delivered emails ${percent(p.clickRate)} → ${percent(c.clickRate)} (${percent(change(c.clickRate, p.clickRate))}); attributed value per delivery $${p.revenuePerDelivery.toFixed(2)} → $${c.revenuePerDelivery.toFixed(2)}.`; }),
    'Prioritize Google headline-theme, Meta hook and Klaviyo welcome-subject proposals after validating real evidence. Amazon and HubSpot declines and Microsoft/Mailchimp improvements remain investigation items. The 20% flags are descriptive materiality, not statistical significance. Attributed outcomes and value stay separate; no total unique purchases or blended ROAS is reported.',
  ].join('\n\n');
  const packet = { ...config, mode: 'simulated', provenance: 'simulated', sources, findings, summary, ...draftProposals(sources), execution: { id: globalThis.crypto.randomUUID(), mode: BROWSER_WEEKLY_MODE, executed_at: new Date().toISOString(), source_operations: 7, completed_steps: 8, model_call_executed: false, provider_api_called: false, external_writes: false, drafting: 'Authored scenario proposals with calculated evidence; no runtime model generation.', scope: 'AURA browser parsing, arithmetic, SHA-256 hashing and proposal validation over authored sample CSVs.' } };
  const errors = validateBrowserSimulation(packet);
  requireValue(errors.length === 0, errors.join(' '));
  packet.execution.validation_checks_passed = true;
  onStep({ key: 'review', status: 'completed', receipt: packet.execution });
  return packet;
}

export async function verifySavedBrowserSimulation(packet) {
  requireValue(validateBrowserSimulation(packet).length === 0, 'Saved simulation validation failed.');
  const authored = browserSimulationInputs(new Date(packet.asOf));
  for (const source of packet.sources) {
    const input = authored.sources.find(item => item.source_key === source.key);
    requireValue(input?.csv_text === source.inputCsv && await sha256(source.inputCsv) === source.execution.input_sha256, 'Saved sample evidence changed.');
    const parsed = parseSimulationSource(input, authored.config);
    requireValue(JSON.stringify(parsed.rows) === JSON.stringify(source.rows), 'Saved metrics do not match their CSV.');
    requireValue(Object.keys(parsed).every(key => JSON.stringify(parsed[key]) === JSON.stringify(source[key])) && source.execution.provider_api_called === false && source.execution.executor === 'AURA browser sample processor', 'Saved source definitions or execution labels changed.');
  }
  requireValue(JSON.stringify(simulationFindings(packet.sources, packet.materialityThreshold)) === JSON.stringify(packet.findings), 'Saved calculations changed.');
  return packet;
}
