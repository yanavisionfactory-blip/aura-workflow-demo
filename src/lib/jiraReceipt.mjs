export function jiraReceiptTasks(receipt = {}) {
  if (!Array.isArray(receipt.issues)) return [];
  let browseBase = null;
  try {
    const url = new URL(receipt.result_url);
    if (url.protocol === "https:" && /^\/browse\/[^/]+\/?$/.test(url.pathname)) {
      browseBase = `${url.origin}/browse/`;
    }
  } catch { /* Jira can provide issue keys without a browser link. */ }
  return receipt.issues
    .filter((issue) => issue && typeof issue.key === "string" && /^[A-Z][A-Z0-9_-]*-\d+$/i.test(issue.key))
    .map((issue, index) => ({
      key: issue.key,
      title: String(receipt.requested_summaries?.[index] || issue.key),
      url: browseBase ? `${browseBase}${encodeURIComponent(issue.key)}` : null,
    }));
}
