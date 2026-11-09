import { savedToolResponse } from "./savedToolResponse.mjs";

export function metaEmptyResultHelp(dataset) {
  if (dataset?.entry.tool !== "Meta Ads" || !dataset.empty) return null;
  const fact = (label) => dataset.facts.find((item) => item.label === label)?.value;
  const account = fact("Account");
  const numericId = /^(?:act_)?(\d+)$/.exec(account || "")?.[1];
  return {
    account,
    accountName: fact("Account name"),
    dates: fact("Reporting dates") || fact("Reporting scope"),
    level: fact("Reporting level"),
    adsManagerUrl: numericId ? `https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=${numericId}` : null,
    steps: [
      "Compare the ad account ID above with the account selected in Meta Ads Manager. Your Meta login and business portfolio have different IDs.",
      "Use the same reporting dates, including the year. Include inactive and archived campaigns when checking campaign history.",
      "If the account differs, change the workflow to the intended ad account. If it is missing from AURA, check that your Facebook login has access to it, then reconnect that Meta connection in Tools.",
      "If the account and dates match and Ads Manager shows activity, share the account ID, date range and a screenshot with AURA support. Keep missing metrics unavailable until the difference is resolved.",
    ],
  };
}

// Separate reads can overlap. Never sum them or merge different accounts.
export function adsInputResult(entries) {
  const summaries = entries.filter((entry) => entry.status === "completed" && entry.hasResponse)
    .map((entry) => ({ entry, ...savedToolResponse(entry) }));
  const fact = (item, label) => item.facts.find((value) => value.label === label)?.value;
  const discovery = summaries.map((item) => item.discovery).filter(Boolean)
    .sort((a, b) => String(a.retrieved_at || "").localeCompare(String(b.retrieved_at || ""))).at(-1);
  return {
    discovery,
    datasets: summaries.filter((item) => !/\.(?:accounts|businesses)\.list$|\.identity\.get$|get_ad_accounts$|^get_account_info$/.test(item.entry.operation || ""))
      .filter((item) => item.campaigns.length || item.records.length || item.body || item.empty).map((item) => {
      const account = fact(item, "Account");
      const matching = account ? summaries.filter((other) => fact(other, "Account") === account) : [];
      const facts = [...item.facts];
      for (const label of ["Account name", "Currency", "Timezone"]) {
        const values = [...new Set(matching.map((other) => fact(other, label)).filter(Boolean))];
        if (!fact(item, label) && values.length === 1) facts.push({ label, value: values[0] });
      }
      return { ...item, facts, label: [item.entry.action, fact(item, "Reporting dates")].filter(Boolean).join(" · ") };
    }),
    summaries,
    accounts: [...new Set(summaries.map((item) => fact(item, "Account")).filter(Boolean))],
  };
}

