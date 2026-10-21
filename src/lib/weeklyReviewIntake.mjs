export const APPROVED_WEEKLY_PREFIX = 'AURA_WEEKLY_REVIEW_V2\n';
export const WEEKLY_PLATFORMS = [
  { key: 'google', name: 'Google Ads', kind: 'paid', aliases: ['Google Ads'] },
  { key: 'meta', name: 'Meta Ads', kind: 'paid', aliases: ['Meta Ads', 'Facebook Ads'] },
  { key: 'microsoft', name: 'Microsoft Advertising', kind: 'paid', aliases: ['Microsoft Advertising', 'Microsoft Ads', 'Bing Ads'] },
  { key: 'amazon', name: 'Amazon Ads', kind: 'paid', aliases: ['Amazon Ads', 'Amazon Advertising'] },
  { key: 'klaviyo', name: 'Klaviyo', kind: 'email', aliases: ['Klaviyo', 'Klaviyo (API Key)'] },
  { key: 'mailchimp', name: 'Mailchimp', kind: 'email', aliases: ['Mailchimp'] },
  { key: 'hubspot', name: 'HubSpot', kind: 'email', aliases: ['HubSpot'] },
];

export function weeklyPeriods(end) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(end) || Number.isNaN(Date.parse(end))) throw new Error('Choose the last complete day of the review week.');
  const day = new Date(`${end}T00:00:00Z`);
  if (day.toISOString().slice(0, 10) !== end) throw new Error("Choose a valid calendar date.");
  const offset = (n) => new Date(day.getTime() + n * 86400000).toISOString().slice(0, 10);
  return { current: { from: offset(-6), to: end, label: `${offset(-6)} – ${end}` }, previous: { from: offset(-13), to: offset(-7), label: `${offset(-13)} – ${offset(-7)}` } };
}

export function weeklyCsvTemplate(key) {
  const platform = WEEKLY_PLATFORMS.find((item) => item.key === key);
  if (!platform) throw new Error('Choose a supported platform.');
  // Empty values are intentional: never seed invented performance into real inputs.
  const columns = platform.kind === 'paid' ? ['impressions', 'clicks', 'spend', 'conversions', 'revenue'] : ['delivered', 'uniqueClicks', 'conversions', 'revenue', 'unsubscribes'];
  return [['id', 'period', 'campaign', ...columns], [`${key}-previous-1`, 'previous', '', ...columns.map(() => '')], [`${key}-current-1`, 'current', '', ...columns.map(() => '')]].map((row) => row.join(',')).join('\r\n');
}

export function weeklySimulatedSource(key, config) {
  const platform = WEEKLY_PLATFORMS.find((item) => item.key === key);
  if (!platform || (!config.simulationOnly && !['meta', 'amazon'].includes(key))) throw new Error('Simulation is available only for Meta Ads and Amazon Ads outside demo mode.');
  const { name, kind } = platform;
  const values = {
    google: [[120000, 3600, 5400, 90, 90000], [130000, 3900, 6240, 78, 78000]],
    meta: [[100000, 1500, 1800, 60, 6000], [105000, 1260, 1890, 45, 4500]],
    microsoft: [[50000, 1500, 1800, 30, 30000], [52000, 1560, 1872, 39, 39000]],
    amazon: [[80000, 800, 1200, 80, 4800], [88000, 880, 1320, 66, 3960]],
    klaviyo: [[10000, 500, 50, 50000, 10], [11000, 385, 33, 33000, 22]],
    mailchimp: [[8000, 240, 24, 24000, 8], [8000, 320, 32, 32000, 8]],
    hubspot: [[6000, 180, 18, 18000, 6], [6600, 132, 13, 13000, 13]],
  }[key];
  const metrics = kind === 'email' ? ['delivered', 'uniqueClicks', 'conversions', 'revenue', 'unsubscribes'] : ['impressions', 'clicks', 'spend', 'conversions', 'revenue'];
  const headers = ['provenance', 'source', 'id', 'period', 'campaign', ...metrics];
  const cohort = { klaviyo: 'welcome journey - new subscribers', mailchimp: 'newsletter - engaged subscribers', hubspot: 'nurture journey - opted-in prospects' }[key] || 'paid campaign';
  const rows = ['previous', 'current'].map((period, i) => ['SIMULATED', name, `SIM-${key}-${period}`, period, `SIMULATED ${name} ${cohort}`, ...values[i]]);
  const attribution = { google: '30-day click; data-driven credits', meta: '7-day click / 1-day view', microsoft: '30-day click; last-click credits', amazon: '14-day click', klaviyo: '5-day email click; opens excluded', mailchimp: '7-day email click; opens excluded', hubspot: '7-day email click; opens excluded' }[key];
  return { source_key: key, input_kind: 'simulated_scenario', periods: config.periods,
    csv_text: [headers, ...rows].map((row) => row.join(',')).join('\r\n'),
    metadata: { provenance: 'simulated', simulationAuthorized: true, simulationOnly: config.simulationOnly === true, filename: `SIMULATED_${key}_ads.csv`,
      report: 'Authored scenario for workflow simulation', timezone: config.timezone, currency: config.currency, asOf: config.asOf,
      attribution: `SIMULATED assumption: ${attribution}`,
      dateBasis: kind === 'email' ? 'SIMULATED assumption: send cohort' : 'SIMULATED assumption: interaction date',
      clickDefinition: kind === 'email' ? 'SIMULATED assumption: unique clicked deliveries per message; bots excluded; not unique people across platforms' : 'SIMULATED assumption: paid link clicks',
      conversionDefinition: 'SIMULATED purchase credits; no actual customer outcomes', revenueDefinition: 'SIMULATED attributed gross value; no actual client revenue',
      simulationNotice: 'SIMULATED — authored sample values, not a connected account, approved export or client result. Replace with verified evidence before implementation.',
      caution: 'Attribution settings and values are scenario assumptions. Validate actual account definitions and mature attribution windows before use. No real account was queried.' } };
}

export function allPlatformSimulationRequest(now = new Date()) {
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  end.setUTCDate(end.getUTCDate() - (end.getUTCDay() || 7));
  const included = WEEKLY_PLATFORMS.map(item => item.key);
  const config = { version: 2, agency: 'SmartSites', simulationOnly: true,
    client: { name: 'Club Furniture — SIMULATED training account', id: 'SIM-CLUB-FURNITURE', fictional: true, engagementConfirmed: false },
    scope: { included, simulated: included, simulationConfirmed: true, confirmed: false, approvalReference: 'User-authorized seven-platform DEMO scope; not a client contract' },
    brief: { goals: 'SIMULATED goals: improve source-specific purchase-credit CPA and ROAS for paid ads; improve unique clicks per delivered email and attributed value per delivery. Use 20% descriptive materiality; do not infer statistical significance or a causal diagnosis. No platform results may be added across sources.',
      brand: 'SIMULATED training brief for a furniture retail scenario. Use only sofas, sectionals and living-room furniture as assumed catalog facts. Warm, straightforward tone. No prices, discounts, shipping, guarantees, manufacturing claims or actual client approval. Klaviyo, Mailchimp and HubSpot cohorts model email journeys/segments only; SMS is excluded.',
      approvalReference: 'User-authorized scenario assumptions; no real client brief approved' },
    reporting: { confirmed: false, destination: 'Internal AURA simulation result and local downloads only' },
    currency: 'USD', timezone: 'UTC', asOf: now.toISOString(), periods: weeklyPeriods(end.toISOString().slice(0, 10)), materialityThreshold: .2,
    expertChecks: ['All seven sources and account scope are simulated.', 'No vendor credentials, reporting APIs, campaigns, budgets, messages or external reporting writes are used.'], references: [] };
  return approvedWeeklyRequest(config, {});
}

export function approvedWeeklyRequest(config, sourceInputs) {
  const allowed = new Set(['version', 'agency', 'client', 'currency', 'timezone', 'asOf', 'materialityThreshold', 'periods', 'scope', 'brief', 'reporting', 'expertChecks', 'references', 'simulationOnly']);
  config = Object.fromEntries(Object.entries(config).filter(([key]) => allowed.has(key)));
  const selected = config.scope.included;
  if (!/^[A-Z]{3}$/.test(config.currency)) throw new Error('Use a three-letter currency code.');
  if (!Number.isFinite(config.materialityThreshold) || config.materialityThreshold <= 0 || config.materialityThreshold > 1) throw new Error('Materiality must be above 0% and at most 100%.');
  if (!/T.*(Z|[+-]\d{2}:\d{2})$/.test(config.asOf) || Number.isNaN(Date.parse(config.asOf))) throw new Error('Enter the actual common extraction cutoff with its timezone, for example 2026-10-20T06:00:00Z.');
  if (Date.parse(config.asOf) > Date.now() + 300000) throw new Error('The extraction cutoff cannot be in the future.');
  if (!selected.length || new Set(selected).size !== selected.length || selected.some((key) => !WEEKLY_PLATFORMS.some((item) => item.key === key))) throw new Error('Select only platforms in the approved client scope.');
  if (config.simulationOnly === true) {
    if (config.client.fictional !== true || config.client.engagementConfirmed !== false || config.scope.confirmed !== false || config.reporting.confirmed !== false) throw new Error('Demo mode cannot claim a verified client, scope or reporting destination.');
  } else if (!config.client.name.trim() || !config.client.id.trim() || !config.client.engagementConfirmed || !config.scope.confirmed || !config.scope.approvalReference.trim()) throw new Error('Confirm the selected client, engagement, account scope and approval reference.');
  if (!config.brief.goals.trim() || !config.brief.brand.trim() || !config.brief.approvalReference.trim()) throw new Error('Provide approved goals, brand guidance and the brief reference.');
  const simulated = config.scope.simulated || [];
  if (new Set(simulated).size !== simulated.length || simulated.some((key) => (!config.simulationOnly && !['meta', 'amazon'].includes(key)) || !selected.includes(key)) || (simulated.length && config.scope.simulationConfirmed !== true)) throw new Error('Explicitly confirm only scoped Meta Ads and Amazon Ads simulations, or use full demo mode.');
  if (config.simulationOnly && (simulated.length !== selected.length || selected.some(key => !simulated.includes(key)))) throw new Error('Demo mode requires every source to be simulated.');
  const sources = selected.map((key) => {
    if (simulated.includes(key)) return weeklySimulatedSource(key, config);
    const input = sourceInputs[key] || {}, platform = WEEKLY_PLATFORMS.find((item) => item.key === key);
    const required = ['accountId', 'approvedBy', 'approvalReference', 'dateBasis', 'attribution', 'conversionDefinition', 'revenueDefinition', 'clickDefinition'];
    if (!input.csv_text?.trim() || required.some((field) => !input[field]?.trim())) throw new Error(`${platform.name}: upload an approved CSV and complete its account and metric definitions.`);
    if (new TextEncoder().encode(input.csv_text).length > 200000) throw new Error(`${platform.name}: aggregate the export to weekly campaign or message cohorts below 200 KB.`);
    return { source_key: key, input_kind: 'approved_export', csv_text: input.csv_text, periods: config.periods,
      metadata: { ...Object.fromEntries(required.map((field) => [field, input[field].trim()])),
        provenance: 'approved_export', filename: input.filename, report: 'Approved weekly campaign / message cohort export',
        timezone: config.timezone, currency: config.currency, asOf: config.asOf,
        caution: input.caution || (platform.kind === 'email' ? 'Clicks are unique per message; totals are not unique people across messages. ' : '') + 'Attribution may restate. Outcomes and value remain separate from other platforms; no causal or statistical significance is established.' } };
  });
  const reporting = config.reporting;
  if (reporting.confirmed && ['destination', 'destinationUrl', 'confirmedBy', 'approvalReference'].some((field) => !reporting[field]?.trim())) throw new Error('Complete the selected account’s reporting confirmation or leave it unconfirmed.');
  if (reporting.confirmed) {
    let url; try { url = new URL(reporting.destinationUrl); } catch { throw new Error('Use an HTTPS reporting destination URL.'); }
    if (url.protocol !== 'https:' || url.username || url.password) throw new Error('Use an HTTPS reporting destination URL without credentials.');
  }
  const packet = { config, sources };
  const json = JSON.stringify(packet), bytes = new TextEncoder().encode(json);
  if (bytes.length > 1600000) throw new Error('The complete review packet must be smaller than 1.6 MB.');
  const content = Array.from(bytes, (byte) => String.fromCharCode(byte)).join('');
  return { prompt: APPROVED_WEEKLY_PREFIX + JSON.stringify({ attachment: 'weekly-review-input.json' }),
    resources: { tools: [], documents: [{ name: 'weekly-review-input.json', size: bytes.length, file_url: 'data:application/json;base64,' + btoa(content) }] } };
}

export function approvedWeeklyMarkdown(packet) {
  const lines = [`# Weekly account review — ${packet.client.name}`, '', `${packet.periods.current.from}–${packet.periods.current.to} vs ${packet.periods.previous.from}–${packet.periods.previous.to}`, `${packet.timezone} · ${packet.currency} · Extracted ${packet.asOf}`, '', packet.summary, '',
    packet.simulationOnly ? 'SIMULATION ONLY. Every source, account scope, goal and brand brief is a demo assumption. No real client approvals or vendor connections are claimed. Vendor reporting APIs were not called.' : packet.provenance === 'mixed_evidence' ? 'SIMULATED SCENARIOS INCLUDED. Source labels distinguish approved exports from authored Meta/Amazon samples. This is a working draft; simulated results are not actual client performance. Vendor reporting APIs were not called.' : 'Approved exports were processed in AURA. Vendor reporting APIs were not called.', 'All tests, copy and backlog items are proposals; no campaigns, budgets, tasks or messages were changed.', '',
    '## Client inputs', '', `Goals: ${packet.brief.goals}`, `Brand: ${packet.brief.brand}`, `Approval reference: ${packet.brief.approvalReference}`, '',
    '## Reporting setup', '', packet.simulationOnly ? 'Internal AURA simulation result and local downloads only. No external destination requested or verified.' : packet.reporting.confirmed ? `Confirmed by ${packet.reporting.confirmedBy}: ${packet.reporting.destination} — ${packet.reporting.destinationUrl}. Reference: ${packet.reporting.approvalReference}. Destination access is user-attested; AURA has not written to or probed it.` : 'UNCONFIRMED — confirm the selected client destination and access before handoff. Draft retained in AURA.', '',
    '## Performance checks', '', 'Weighted rates use summed numerators and denominators. Attributed outcome credits and value are separate per platform; no blended ROAS or deduplicated orders. Material changes are descriptive, not statistically significant.'];
  for (const finding of packet.findings || []) lines.push(`- ${finding.provenance === 'simulated' ? 'SIMULATED — ' : ''}${finding.source} ${finding.metric}: ${finding.previous ?? 'unavailable'} → ${finding.current ?? 'unavailable'}; change ${finding.change == null ? 'no comparable baseline' : (100 * finding.change).toFixed(1) + '%'}. Evidence: ${finding.evidence.join(', ')}.`);
  lines.push('', '## Proposed experiments');
  for (const experiment of packet.experiments) {
    lines.push('', `### ${experiment.id} — ${experiment.title}`, experiment.simulationBased ? 'SIMULATION-BASED PROPOSAL — validate on actual account data before implementation.' : 'Approved-export evidence; proposed only.', `Platform: ${experiment.source}; evidence: ${experiment.evidence.join(', ')}`);
    for (const key of ['hypothesis', 'change', 'design', 'primary', 'guardrails', 'decision', 'feasibility', 'owner', 'effort']) lines.push(`${key}: ${experiment[key]}`);
    lines.push(`Dependencies: ${experiment.dependencies.join(', ') || 'None'}`);
  }
  lines.push('', '## Draft variants');
  for (const creative of packet.creatives) {
    lines.push('', `### ${creative.id} — ${creative.title}`, creative.simulationBased ? 'SIMULATION-BASED DRAFT — validate evidence before implementation.' : 'Draft only.', creative.note, `Experiment: ${creative.experiment}`);
    for (const variant of creative.variants) {
      lines.push('', variant.label);
      for (const [key, value] of Object.entries(variant)) if (key !== 'label' && (Array.isArray(value) ? value.length : value)) lines.push(`${key}: ${Array.isArray(value) ? value.join(' | ') : value}`);
    }
    for (const [key, value] of Object.entries(creative.shared)) if (value) lines.push(`${key}: ${value}`);
  }
  lines.push('', '## Implementation backlog');
  for (const item of packet.backlog) lines.push('', `### ${item.id} — ${item.priority} — ${item.title}`, item.simulationBased ? 'SIMULATION-BASED — real-data validation required.' : 'Approved-export evidence.', `Proposed owner: ${item.owner}; effort: ${item.effort}`, item.fix, `Reasoning: ${item.reasoning}`, `Acceptance: ${item.acceptance}`, `Dependencies: ${item.dependencies.join(', ') || 'None'}`, `Evidence: ${item.evidence.join(', ')}`, 'Status: proposed');
  lines.push('', '## Source register');
  for (const source of packet.sources) lines.push('', `### ${source.name}`, `Account: ${source.accountId}`, source.provenance === 'simulated' ? source.simulationNotice : `Export: ${source.filename}; approved by ${source.approvedBy}; reference ${source.approvalReference}`, `Attribution: ${source.attribution}`, `Date basis: ${source.dateBasis}`, `Clicks: ${source.clickDefinition}`, `Outcome: ${source.conversionDefinition}`, `Value: ${source.revenueDefinition}`, `Caution: ${source.caution}`, `SHA-256: ${source.execution.input_sha256}`, `Evidence IDs: ${source.rows.map((row) => row.id).join(', ')}`);
  return lines.join('\n');
}
