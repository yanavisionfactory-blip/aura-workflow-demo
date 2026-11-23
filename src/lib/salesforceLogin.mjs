export function salesforceLoginHost(value) {
  const text = value.trim();
  try {
    const url = new URL(text.includes("://") ? text : `https://${text}`);
    if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
    const match = /^([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.sandbox)?)\.(?:lightning\.force|my\.salesforce)\.com$/.exec(url.hostname);
    return match ? `${match[1]}.my.salesforce.com` : null;
  } catch {
    return null;
  }
}
