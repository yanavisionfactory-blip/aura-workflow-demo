import { adsInputResult } from "./adsInputResult.mjs";

function canvaUrl(value, designId, embed = false) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || !["canva.com", "www.canva.com"].includes(url.hostname)
      || url.username || url.password || url.port) return null;
    if (embed) {
      // Only a provider-supplied embed for this exact design. An editor/view
      // link is not permission to publish the design or manufacture an embed.
      if (!designId || url.pathname.split("/")[2] !== designId
        || !/^\/design\/[^/]+\/(?:[^/]+\/)?view$/.test(url.pathname)
        || !url.searchParams.has("embed")) return null;
    } else if (!/^\/(?:api\/)?design\/[^/]+\/(?:[^/]+\/)?(?:edit|view)$/.test(url.pathname)) return null;
    return url.href;
  } catch { return null; }
}

export function nativeToolView(tool, entries = [], result = {}) {
  if (tool === "Canva" && result.kind === "presentation") {
    const link = canvaUrl(result.link) || canvaUrl(result.viewLink);
    return {
      title: "Canva editor", detail: result.title, embedUrl: canvaUrl(result.embedUrl, result.designId, true),
      targets: link ? [{ link, label: "Open in Canva" }] : [],
      note: link ? "Opens the actual design in Canva in a new tab. Use the Canva account connected to this workflow."
        : "No saved design link is available. Check the saved actions below.",
      help: "An embedded Canva view is available only when the design has an authorized embed link.",
    };
  }
  if (!["Google Ads", "Meta Ads"].includes(tool)) return null;
  const completed = entries.filter((entry) => entry.status === "completed" && entry.hasResponse && !entry.synthetic && !entry.source);
  if (!completed.length) return null;
  const model = adsInputResult(completed);
  const reports = model.datasets.length ? model.datasets : model.summaries;
  const accounts = [...new Set(reports.flatMap((item) => item.facts.filter((fact) => fact.label === "Account").map((fact) => fact.value)))];
  const meta = tool === "Meta Ads";
  const valid = accounts.map((account) => String(account).replace(meta ? /^act_/ : /-/g, ""))
    .filter((id) => meta ? /^\d+$/.test(id) : /^\d{10}$/.test(id));
  const ids = [...new Set(valid)];
  // Google's UI uses opaque account identifiers, not the API customer ID.
  // Keep the verified customer ID visible instead of guessing an ocid URL.
  const base = meta ? "https://adsmanager.facebook.com/adsmanager/manage/campaigns" : "https://ads.google.com/aw/campaigns";
  return {
    title: meta ? "Meta Ads Manager" : "Google Ads campaigns",
    detail: "Live tool interface", accounts: ids,
    targets: meta && ids.length ? ids.map((id) => ({ link: `${base}?act=${id}`, label: ids.length > 1 ? `Open account ${id}` : "Open in Meta Ads", account: id }))
      : [{ link: base, label: `Open in ${tool}` }],
    note: meta ? "Opens Ads Manager in a new tab. Sign in with access to the ad account used by this workflow."
      : ids.length ? "Opens Google Ads in a new tab. Select the customer account shown here; Google may open your last-used account first."
        : "Opens Google Ads in a new tab. No customer account ID was saved with this result; choose the account connected to this workflow.",
    help: "The live account may show a different date range. The saved snapshot below preserves the data used in this report.",
  };
}
