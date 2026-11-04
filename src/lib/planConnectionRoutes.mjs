const APP_ROUTES = { "Google Sheets": "google-sheets", "Google Docs": "google-docs" };

export function alternativePlanConnection(tool, catalog = []) {
  const provider = APP_ROUTES[tool.name];
  if (!provider || !["google", "google-workspace"].includes(tool.provider)) return null;
  const entry = catalog.find((item) => item.name === tool.name);
  if (!entry?.preferredConnection || !entry.connectable || entry.provider !== provider
    || entry.connectionBackend !== "pipedream"
    || !entry.routes?.some((route) => route.provider === provider && route.connectable)) return null;
  return provider;
}

export function planConnectionRevision(tool, provider, currentRoutes = {}) {
  if (APP_ROUTES[tool.name] !== provider) throw new Error("This connection is not available for this app.");
  return {
    instruction: `Use the dedicated ${tool.name} connection for every ${tool.name} action and verification read. ` +
      "Preserve the reviewed result, contents and scope. Rebuild the executable steps using that connection's supported operations. " +
      "Show the complete revised plan for review before any external action.",
    connectionRoutes: { ...currentRoutes, [provider.replace("google-", "")]: provider },
  };
}
