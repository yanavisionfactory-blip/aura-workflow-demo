export function nativeDiscoveryRows(response, tool) {
  if (!response || response.isError || response.error) return [];
  const candidates = tool === 'google'
    ? [response.ret, response.options, response.os]
    : [response.lists, response.ret?.lists];
  return candidates.find(value => Array.isArray(value) && value.length) || [];
}

export function marketingPeriodRows(packet, period = 'current', search = '') {
  const query = search.trim().toLowerCase();
  return (packet?.rows || []).filter(row => row.period === period
    && (!query || row.campaign.toLowerCase().includes(query)));
}

export function sourcePurchaseCpa(row) {
  return row.purchases > 0 ? row.spend / row.purchases : null;
}
