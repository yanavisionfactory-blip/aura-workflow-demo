const normalized = (value) => String(value || "").trim().toLowerCase();

export function matchingConnections(tools, toolName, provider) {
  const name = normalized(toolName);
  const slug = name.replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const providerSlug = normalized(provider);
  return (tools || []).filter((tool) => {
    const toolSlug = normalized(tool.slug);
    const displayName = normalized(tool.display_name);
    return displayName === name || toolSlug === slug || (providerSlug && toolSlug === providerSlug);
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

  throw new Error(`Choose which ${toolName} account you want AURA to use.`);
}

export function isVerifiedConnection(result) {
  return result?.status === "verified" && result?.verification?.ok === true;
}
