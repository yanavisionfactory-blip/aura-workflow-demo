export const ratio = (a, b) => b > 0 ? a / b : null;
export const change = (current, previous) => previous > 0 ? current / previous - 1 : null;
export const dollars = (n) => n === null || n === undefined ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(n);
export const number = (n) => n === null || n === undefined ? '—' : new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(n);
export const percent = (n, digits = 1) => n === null || n === undefined ? '—' : `${(n * 100).toFixed(digits)}%`;
export const delta = (n) => n === null ? 'No comparable baseline' : `${n > 0 ? '+' : ''}${percent(n)}`;
const sum = (rows, field) => rows.reduce((total, row) => total + (row[field] || 0), 0);

export function totals(source, period) {
  const rows = source.rows.filter((row) => row.period === period);
  if (source.kind === 'paid') {
    const impressions = sum(rows, 'impressions'), clicks = sum(rows, 'clicks'), spend = sum(rows, 'spend');
    const purchases = sum(rows, 'purchases'), revenue = sum(rows, 'revenue');
    return { impressions, clicks, spend, purchases, revenue, ctr: ratio(clicks, impressions), cpc: ratio(spend, clicks), cpa: ratio(spend, purchases), roas: ratio(revenue, spend) };
  }
  const delivered = sum(rows, 'delivered'), uniqueClicks = sum(rows, 'uniqueClicks'), purchases = sum(rows, 'purchases'), revenue = sum(rows, 'revenue');
  return { delivered, uniqueClicks, purchases, revenue, unsubscribes: sum(rows, 'unsubscribes'), clickRate: ratio(uniqueClicks, delivered), revenuePerDelivery: ratio(revenue, delivered) };
}

export function evidenceRows(packet, refs) {
  return refs.map((id) => {
    for (const source of packet.sources) {
      const row = [...source.rows, ...(source.searchTerms || [])].find((item) => item.id === id);
      if (row) return { source, row };
    }
    return { missing: id };
  });
}

export function reviewModel(packet) {
  const platforms = packet.sources.map((source) => ({ source, current: totals(source, 'current'), previous: totals(source, 'previous') }));
  const paidSpend = platforms.filter((item) => item.source.kind === 'paid').reduce((total, item) => total + item.current.spend, 0);
  const paidSpendPrevious = platforms.filter((item) => item.source.kind === 'paid').reduce((total, item) => total + item.previous.spend, 0);
  const gCurrent = evidenceRows(packet, ['G-C-NONBRAND'])[0].row, gPrevious = evidenceRows(packet, ['G-P-NONBRAND'])[0].row;
  const mCurrent = evidenceRows(packet, ['M-C-VIDEO'])[0].row, mPrevious = evidenceRows(packet, ['M-P-VIDEO'])[0].row;
  const kCurrent = packet.sources.find((item) => item.key === 'klaviyo').rows.filter((row) => row.period === 'current' && row.channel === 'Campaign');
  const kPrevious = packet.sources.find((item) => item.key === 'klaviyo').rows.filter((row) => row.period === 'previous' && row.channel === 'Campaign');
  const emailCurrentRate = ratio(sum(kCurrent, 'uniqueClicks'), sum(kCurrent, 'delivered'));
  const emailPreviousRate = ratio(sum(kPrevious, 'uniqueClicks'), sum(kPrevious, 'delivered'));
  const findings = [
    { id: 'F1', source: 'google', experiment: 'E1', title: 'Non-brand acquisition became more expensive', current: ratio(gCurrent.spend, gCurrent.purchases), previous: ratio(gPrevious.spend, gPrevious.purchases), metric: 'Purchase-credit CPA', format: 'money', evidence: ['G-C-NONBRAND', 'G-P-NONBRAND', 'Q-C-GENERIC', 'Q-P-GENERIC'], interpretation: 'CPA doubled while the generic query share of non-brand spend increased. Query mix, auction prices and landing experience are possible explanations; this weekly comparison does not identify a cause.' },
    { id: 'F2', source: 'meta', experiment: 'E2', title: 'The prospecting video needs a creative review', current: ratio(mCurrent.spend, mCurrent.purchases), previous: ratio(mPrevious.spend, mPrevious.purchases), metric: 'Attributed purchase CPA', format: 'money', evidence: ['M-C-VIDEO', 'M-P-VIDEO'], interpretation: 'Video CPA rose from $25 to $60; link CTR fell from 1.5% to 1.0%, while frequency rose from 2.86 to 4.00. This is consistent with creative wear-out, but audience or auction changes could also explain it.' },
    { id: 'F3', source: 'klaviyo', experiment: 'E3', title: 'Campaign click rate fell as the audience mix changed', current: emailCurrentRate, previous: emailPreviousRate, metric: 'Per-message unique click rate', format: 'percent', evidence: ['K-C-ENGAGED', 'K-C-OTHER', 'K-P-ENGAGED', 'K-P-OTHER'], interpretation: 'Campaign click rate fell from 2.4% to 1.2%. The engaged share of deliveries also changed from 50.0% to 41.7%, so the overall decline cannot be attributed to the subject line. Compare segments before testing.' },
  ].map((item) => ({ ...item, change: change(item.current, item.previous), material: Math.abs(change(item.current, item.previous) || 0) >= packet.materialityThreshold }));
  return { platforms, paidSpend, paidSpendPrevious, paidSpendChange: change(paidSpend, paidSpendPrevious), findings };
}

export function validatePacket(packet) {
  const errors = [], ids = new Set();
  const validPeriod = (value) => /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value));
  for (const period of Object.values(packet.periods)) {
    if (!validPeriod(period.from) || !validPeriod(period.to) || (Date.parse(period.to) - Date.parse(period.from)) / 86400000 !== 6) errors.push('Reporting periods must contain seven complete calendar days.');
  }
  if (Date.parse(packet.periods.current.from) - Date.parse(packet.periods.previous.to) !== 86400000) errors.push('Comparison periods must be consecutive.');
  if (packet.sources.length !== packet.scope.included.length || packet.sources.some((source) => !packet.scope.included.includes(source.key))) errors.push('A source falls outside the selected scope.');
  for (const source of packet.sources) {
    if (source.provenance !== 'simulated') errors.push('This public demo accepts labelled simulated sources only.');
    if (source.currency !== packet.currency || source.timezone !== packet.timezone || source.asOf !== packet.asOf) errors.push(`${source.name}: currency, timezone or extraction cutoff does not align.`);
    if (!source.attribution || !source.dateBasis || !source.revenueDefinition) errors.push(`${source.name}: metric definitions are incomplete.`);
    for (const row of [...source.rows, ...(source.searchTerms || [])]) {
      if (ids.has(row.id)) errors.push(`Duplicate evidence ID: ${row.id}`);
      ids.add(row.id);
      if (!['current', 'previous'].includes(row.period)) errors.push(`Unknown period: ${row.id}`);
      for (const [key, value] of Object.entries(row)) if (typeof value === 'number' && (!Number.isFinite(value) || value < 0)) errors.push(`Invalid ${key}: ${row.id}`);
      if (row.clicks > row.impressions || row.uniqueClicks > row.delivered || row.unsubscribes > row.delivered) errors.push(`Invalid denominator: ${row.id}`);
    }
  }
  if (packet.experiments.length !== 3) errors.push('Exactly three proposed experiments are required.');
  for (const item of [...packet.experiments, ...packet.backlog]) {
    if (!item.evidence.length || evidenceRows(packet, item.evidence).some((row) => row.missing)) errors.push(`Unresolved evidence: ${item.id}`);
    if (item.status !== 'proposed') errors.push(`A proposal cannot be marked executed: ${item.id}`);
  }
  for (const creative of packet.creatives) {
    if (creative.source === 'google') for (const variant of creative.variants) {
      if (variant.headlines.some((line) => [...line].length > 30) || variant.descriptions.some((line) => [...line].length > 90)) errors.push('Google Search copy exceeds the checked character limits.');
    }
  }
  return errors;
}

export function checks(packet) {
  const errors = validatePacket(packet);
  return [
    { status: errors.length ? 'failed' : 'checked', title: 'Fixture arithmetic, scope and evidence references', detail: errors.join(' ') || 'All source rows have valid denominators and unique evidence IDs; all proposals resolve to scoped source rows.' },
    { status: 'checked', title: 'Complete periods and one extraction cutoff', detail: `${packet.periods.current.from}–${packet.periods.current.to} vs ${packet.periods.previous.from}–${packet.periods.previous.to}; ${packet.timezone}; ${packet.currency}; as of ${packet.asOf}.` },
    { status: 'checked', title: 'Attribution is kept separate', detail: 'Spend is added across the two paid platforms. Revenue and purchase credits stay within each platform; no blended ROAS, total unique orders or incremental lift is claimed.' },
    { status: 'checked', title: 'Three experiments and draft copy', detail: 'Exactly three evidence-linked proposals; Google Search headline and description lengths checked. All copy remains a draft.' },
    { status: 'review', title: 'Real client scope, goals and brand approval', detail: 'The client and brand brief are fictional scenario assumptions. A real engagement, approved exports and account mapping have not been confirmed.' },
    { status: 'review', title: 'Attribution maturity and statistical inference', detail: 'Recent cohorts can restate as conversion windows close. Weekly movements are descriptive; test power and sample sizes need analyst approval before any live test.' },
    { status: 'review', title: 'Selected client reporting destination', detail: 'SmartSites publicly describes its Client Hub. This selected account’s destination, URL and permissions remain unconfirmed; the report preview stays inside AURA.' },
  ];
}

export function sourceCsv(packet, key) {
  const source = packet.sources.find((item) => item.key === key);
  if (!source) throw new Error('Source is outside this review’s scope.');
  const records = [...source.rows.map((row) => ({ ...row, recordType: source.kind === 'email' ? 'message_cohort' : 'campaign_or_adset' })), ...(source.searchTerms || []).map((row) => ({ ...row, recordType: 'nonbrand_search_term_breakdown_do_not_add_to_campaigns' }))];
  const columns = ['provenance', 'source', 'recordType', 'id', 'period', 'period_start', 'period_end', 'timezone', 'currency', 'asOf', 'campaign', 'channel', 'segment', 'impressions', 'clicks', 'spend', 'purchases', 'revenue', 'reach', 'delivered', 'uniqueClicks', 'unsubscribes', 'attribution', 'dateBasis'];
  const quote = (value) => `"${String(value ?? '').replaceAll('"', '""')}"`;
  return [columns, ...records.map((row) => {
    const record = { ...row, provenance: 'SIMULATED', source: source.name, period_start: packet.periods[row.period].from, period_end: packet.periods[row.period].to, timezone: source.timezone, currency: source.currency, asOf: source.asOf, attribution: source.attribution, dateBasis: source.dateBasis };
    return columns.map((column) => record[column]);
  })].map((row) => row.map(quote).join(',')).join('\r\n');
}
