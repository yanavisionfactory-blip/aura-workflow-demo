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

export function approvedWeeklyRequest(config, sourceInputs) {
  const allowed = new Set(['version', 'agency', 'client', 'currency', 'timezone', 'asOf', 'materialityThreshold', 'periods', 'scope', 'brief', 'reporting', 'expertChecks', 'references']);
  config = Object.fromEntries(Object.entries(config).filter(([key]) => allowed.has(key)));
  const selected = config.scope.included;
  if (!/^[A-Z]{3}$/.test(config.currency)) throw new Error('Use a three-letter currency code.');
  if (!Number.isFinite(config.materialityThreshold) || config.materialityThreshold <= 0 || config.materialityThreshold > 1) throw new Error('Materiality must be above 0% and at most 100%.');
  if (!/T.*(Z|[+-]\d{2}:\d{2})$/.test(config.asOf) || Number.isNaN(Date.parse(config.asOf))) throw new Error('Enter the actual common extraction cutoff with its timezone, for example 2026-10-20T06:00:00Z.');
  if (Date.parse(config.asOf) > Date.now() + 300000) throw new Error('The extraction cutoff cannot be in the future.');
  if (!selected.length || new Set(selected).size !== selected.length || selected.some((key) => !WEEKLY_PLATFORMS.some((item) => item.key === key))) throw new Error('Select only platforms in the approved client scope.');
  if (!config.client.name.trim() || !config.client.id.trim() || !config.client.engagementConfirmed || !config.scope.confirmed || !config.scope.approvalReference.trim()) throw new Error('Confirm the selected client, engagement, account scope and approval reference.');
  if (!config.brief.goals.trim() || !config.brief.brand.trim() || !config.brief.approvalReference.trim()) throw new Error('Provide approved goals, brand guidance and the brief reference.');
  const sources = selected.map((key) => {
    const input = sourceInputs[key] || {}, platform = WEEKLY_PLATFORMS.find((item) => item.key === key);
    const required = ['accountId', 'approvedBy', 'approvalReference', 'dateBasis', 'attribution', 'conversionDefinition', 'revenueDefinition'];
    if (!input.csv_text?.trim() || required.some((field) => !input[field]?.trim())) throw new Error(`${platform.name}: upload an approved CSV and complete its account and metric definitions.`);
    if (new TextEncoder().encode(input.csv_text).length > 200000) throw new Error(`${platform.name}: aggregate the export to weekly campaign or message cohorts below 200 KB.`);
    return { source_key: key, input_kind: 'approved_export', csv_text: input.csv_text, periods: config.periods,
      metadata: { ...Object.fromEntries(required.map((field) => [field, input[field].trim()])),
        provenance: 'approved_export', filename: input.filename, report: 'Approved weekly campaign / message cohort export',
        timezone: config.timezone, currency: config.currency, asOf: config.asOf,
        caution: input.caution || 'Attribution may restate. Outcomes and value remain separate from other platforms; no causal or statistical significance is established.' } };
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
    'Approved exports were processed in AURA. Vendor reporting APIs were not called. All tests, copy and backlog items are proposals; no campaigns, budgets, tasks or messages were changed.', '',
    '## Client inputs', '', `Goals: ${packet.brief.goals}`, `Brand: ${packet.brief.brand}`, `Approval reference: ${packet.brief.approvalReference}`, '',
    '## Reporting setup', '', packet.reporting.confirmed ? `Confirmed by ${packet.reporting.confirmedBy}: ${packet.reporting.destination} — ${packet.reporting.destinationUrl}. Reference: ${packet.reporting.approvalReference}. Destination access is user-attested; AURA has not written to or probed it.` : 'UNCONFIRMED — confirm the selected client destination and access before handoff. Draft retained in AURA.', '',
    '## Performance checks', '', 'Weighted rates use summed numerators and denominators. Attributed outcome credits and value are separate per platform; no blended ROAS or deduplicated orders. Material changes are descriptive, not statistically significant.'];
  for (const finding of packet.findings || []) lines.push(`- ${finding.source} ${finding.metric}: ${finding.previous ?? 'unavailable'} → ${finding.current ?? 'unavailable'}; change ${finding.change == null ? 'no comparable baseline' : (100 * finding.change).toFixed(1) + '%'}. Evidence: ${finding.evidence.join(', ')}.`);
  lines.push('', '## Proposed experiments');
  for (const experiment of packet.experiments) {
    lines.push('', `### ${experiment.id} — ${experiment.title}`, `Platform: ${experiment.source}; evidence: ${experiment.evidence.join(', ')}`);
    for (const key of ['hypothesis', 'change', 'design', 'primary', 'guardrails', 'decision', 'feasibility', 'owner', 'effort']) lines.push(`${key}: ${experiment[key]}`);
    lines.push(`Dependencies: ${experiment.dependencies.join(', ') || 'None'}`);
  }
  lines.push('', '## Draft variants');
  for (const creative of packet.creatives) {
    lines.push('', `### ${creative.id} — ${creative.title}`, creative.note, `Experiment: ${creative.experiment}`);
    for (const variant of creative.variants) {
      lines.push('', variant.label);
      for (const [key, value] of Object.entries(variant)) if (key !== 'label' && (Array.isArray(value) ? value.length : value)) lines.push(`${key}: ${Array.isArray(value) ? value.join(' | ') : value}`);
    }
    for (const [key, value] of Object.entries(creative.shared)) if (value) lines.push(`${key}: ${value}`);
  }
  lines.push('', '## Implementation backlog');
  for (const item of packet.backlog) lines.push('', `### ${item.id} — ${item.priority} — ${item.title}`, `Proposed owner: ${item.owner}; effort: ${item.effort}`, item.fix, `Reasoning: ${item.reasoning}`, `Acceptance: ${item.acceptance}`, `Dependencies: ${item.dependencies.join(', ') || 'None'}`, `Evidence: ${item.evidence.join(', ')}`, 'Status: proposed');
  lines.push('', '## Source register');
  for (const source of packet.sources) lines.push('', `### ${source.name}`, `Account: ${source.accountId}`, `Export: ${source.filename}; approved by ${source.approvedBy}; reference ${source.approvalReference}`, `Attribution: ${source.attribution}`, `Date basis: ${source.dateBasis}`, `Outcome: ${source.conversionDefinition}`, `Value: ${source.revenueDefinition}`, `Caution: ${source.caution}`, `SHA-256: ${source.execution.input_sha256}`, `Evidence IDs: ${source.rows.map((row) => row.id).join(', ')}`);
  return lines.join('\n');
}
