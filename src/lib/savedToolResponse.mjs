// Human-facing summaries from saved receipts. Never turn missing metrics into 0.
export const responseBody = (value) => value?.ret ?? value ?? {};
const number = (value) => (typeof value === "number" || typeof value === "string" && value.trim() !== "") && Number.isFinite(Number(value)) ? Number(value) : null;
const read = (object, ...keys) => keys.map((key) => object?.[key]).find((value) => value !== undefined);
const ratio = (a, b) => a !== null && b !== null && b !== 0 ? a / b : null;
const format = (value, digits = 2) => value === null ? "Unavailable" : value.toLocaleString("en-US", { maximumFractionDigits: digits });

export function savedToolResponse(entry) {
  const body = responseBody(entry.response);
  const rows = Array.isArray(body) ? body : Array.isArray(body.results) ? body.results : Array.isArray(body.data) ? body.data : null;
  const args = entry.inputs || {};
  const google = entry.tool === "Google Ads";
  const meta = entry.tool === "Meta Ads";
  const reddit = entry.tool === "Reddit Ads";
  const discovery = body.account_discovery;
  const account = body.account || rows?.[0]?.customer || {};
  const facts = [];
  const fact = (label, value) => { if (value !== undefined && value !== null && value !== "") facts.push({ label, value: String(value) }); };
  if (google || meta || reddit) {
    fact("Account", body.account_id || account.id || args.customer_id || args.customerId || args.customerClientId || args.account_id || args.accountId || args.ad_account_id);
    fact("Account name", account.name || account.descriptiveName || account.descriptive_name);
    fact("Currency", account.currency || account.currencyCode || account.currency_code);
    fact("Timezone", account.timezone_name || account.timeZone || account.time_zone || account.time_zone_id);
    const date = body.date_range;
    fact("Reporting dates", date?.since && date?.until ? `${date.since} – ${date.until}` : date?.starts_at && date?.ends_at ? `${date.starts_at} – ${date.ends_at}` : args.startDate && args.endDate ? `${args.startDate} – ${args.endDate}` : undefined);
    if (google && !args.query && !body.query && /create-.*-report$/.test(entry.operation || "")) fact("Reporting scope", args.dateRange || "Full available history · no date filter");
    fact("Retrieved", body.retrieved_at);
    if (discovery) {
      fact("Account discovery", discovery.coverage?.status === "complete" ? "Completed for authorized accounts" : "Incomplete · some account access could not be checked");
      fact("Discovered accounts", discovery.accounts?.map((row) => `${row.name || "Account"} · ${row.ad_account_id || row.id}`).join("; "));
      fact("Access limitations", discovery.coverage?.warnings?.join(" "));
    }
    const query = body.query || args.query;
    if (google && typeof query === "string") fact("Reporting scope", /segments\.(date|week|month|quarter|year)/i.test(query) ? "Date selection recorded in the saved Google Ads query" : "No reporting-date filter in the saved Google Ads query");
  }
  const campaigns = (google || meta || reddit) && rows ? rows.filter((row) => row.campaign || row.campaign_name || row.metrics || row.spend !== undefined).map((row) => {
    const m = row.metrics || row;
    const spend = google ? number(read(m, "costMicros", "cost_micros")) : number(m.spend);
    const cost = google && spend !== null ? spend / 1e6 : spend;
    const impressions = number(m.impressions), clicks = number(m.clicks), conversions = google ? number(m.conversions) : reddit ? number(m.purchase_conversions) : null;
    const value = google ? number(read(m, "conversionsValue", "conversions_value")) : reddit ? number(m.purchase_conversion_value) : null;
    return { id: row.campaign?.id || row.campaign_id, title: row.campaign?.name || row.campaign_name || "Campaign result", status: row.campaign?.status || row.status,
      dates: row.date_start && row.date_stop ? `${row.date_start} – ${row.date_stop}` : row.segments?.date,
      currency: row.customer?.currencyCode || row.customer?.currency_code || row.account_currency || account.currency,
      metrics: [["Spend", cost], ["Impressions", impressions], ["Clicks", clicks], ["CTR", ratio(clicks, impressions)], ["CPC", ratio(cost, clicks)], ["Conversions", conversions], ["CPA", ratio(cost, conversions)], ["Conversion value", value], ["ROAS", ratio(value, cost)]]
        .map(([label, value]) => ({ label, value: label === "CTR" && typeof value === "number" ? `${format(value * 100)}%` : format(typeof value === "number" ? value : null, label === "ROAS" ? 3 : 2) })) };
  }) : [];
  const empty = rows !== null && rows.length === 0;
  const summary = typeof entry.response?.exports?.$summary === "string" ? entry.response.exports.$summary
    : typeof body.summary === "string" ? body.summary : null;
  return { facts, campaigns, empty, discovery, count: rows?.length,
    title: typeof body.title === "string" ? body.title : null,
    body: typeof body.body === "string" ? body.body : typeof body.text === "string" ? body.text : null,
    records: !campaigns.length && rows ? rows.map((row) => ({ title: row.text || row.keyword || row.name || row.title, description: row.description })).filter((row) => row.title) : [],
    summary: empty ? "No records returned for this request. Metrics are unavailable, not zero."
      : campaigns.length ? `${campaigns.length} campaign ${campaigns.length === 1 ? "result" : "results"} returned.`
      : summary || (rows ? `${rows.length} ${rows.length === 1 ? "record" : "records"} returned.` : "Action completed. Its saved receipt is available in workflow activity."),
    note: google && campaigns.length ? "Conversion value is provider-reported and is not verified sales revenue. Conversion definitions and attribution windows require the account’s configuration."
      : reddit ? "Conversions and conversion value are Reddit-attributed purchases. Other event types are not included."
      : meta && empty ? "This applies to the requested account and dates. It does not establish that earlier history or other accounts have no activity." : null,
  };
}
