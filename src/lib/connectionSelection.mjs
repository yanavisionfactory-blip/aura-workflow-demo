const normalized = (value) => String(value || "").trim().toLowerCase();

const GOOGLE_FAMILY_OPERATION = {
  "google calendar": "calendar.",
  "google docs": "docs.",
  "google drive": "drive.",
  "google sheets": "sheets.",
  gmail: "gmail.",
};

export function matchingConnections(tools, toolName, provider) {
  const name = normalized(toolName);
  const slug = name.replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const providerSlug = normalized(provider);
  return (tools || []).filter((tool) => {
    const toolSlug = normalized(tool.slug);
    const canonicalProvider = normalized(tool.canonical_provider);
    const displayName = normalized(tool.display_name);
    const googleOperation = GOOGLE_FAMILY_OPERATION[name];
    const sharedGoogleAccount = toolSlug === "google" && googleOperation
      && (tool.allowed_operations || []).some((operation) => operation.startsWith(googleOperation));
    if (toolSlug === "google" && googleOperation && !sharedGoogleAccount) return false;
    return displayName === name || toolSlug === slug || canonicalProvider === slug ||
      sharedGoogleAccount ||
      (providerSlug && (toolSlug === providerSlug || canonicalProvider === providerSlug));
  });
}

export function selectConnection(tools, { toolName, provider, connectionId } = {}) {
  const matches = matchingConnections(tools, toolName, provider);
  if (connectionId) {
    return matches.find((tool) => tool.id === connectionId) || null;
  }
  if (matches.length <= 1) return matches[0] || null;

  const verified = matches.filter(
    (tool) => tool.enabled && tool.status === "verified" && tool.verification?.ok !== false
  );
  if (verified.length === 1) return verified[0];
  const accountFamilies = new Set(
    verified.map((tool) => tool.external_account_id).filter(Boolean)
  );
  if (verified.length > 1 && accountFamilies.size === 1) {
    return verified.find((tool) => normalized(tool.slug) === normalized(provider)) || verified[0];
  }

  throw new Error(`Choose which ${toolName} account you want AURA to use.`);
}

export function isVerifiedConnection(result) {
  return result?.status === "verified" && result?.verification?.ok === true;
}
