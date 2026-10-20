export const toolNames = { google_ads: 'Google Ads', google_business_profile: 'Google Business Profile', facebook: 'Facebook', instagram: 'Instagram', linkedin: 'LinkedIn', x: 'X / Twitter', crm: 'CRM', appointments: 'Appointment system', analytics: 'Analytics', reporting: 'Reporting and goals' };
export const metricLabel = (metric) => ({ tracked_lead_credits: 'Platform lead credits — not unique leads', tracked_cpa: 'Cost per platform lead credit', booked: 'Appointments booked', attended: 'Appointments attended', booked_people: 'Unique people booked', attended_people: 'Unique people attended', leads: 'Unique leads received', qualified_leads: 'Qualified received leads', customers: 'New customers', ctr: 'Paid click-through rate', cpc: 'Cost per paid click', organic_engagement_rate: 'Organic engagement / impressions', paid_spend: 'Total paid media spend' }[metric] || metric.replaceAll('_', ' '));
export const formatValue = (value, unit = 'count') => value === null || value === undefined ? 'N/A' : unit === 'USD' ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value) : unit === 'rate' ? `${(value * 100).toFixed(2)}%` : new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value);
export const formatChange = (row) => row.unit === 'rate' ? (row.delta === null ? 'N/A' : `${row.delta >= 0 ? '+' : ''}${(row.delta * 100).toFixed(2)} pp`) : row.change === null ? 'N/A' : `${row.change >= 0 ? '+' : ''}${(row.change * 100).toFixed(1)}%`;
export function findEvidence(packet, id) {
  for (const source of packet.sources || []) {
    const row = source.rows.find((item) => item.id === id);
    if (row) return { source, row };
  }
  return null;
}
export function reviewDownload(packet) {
  return JSON.stringify({ label: 'REAL PUBLIC CLIENT CONTEXT — ALL REVIEW DATA SIMULATED', ...packet }, null, 2);
}
