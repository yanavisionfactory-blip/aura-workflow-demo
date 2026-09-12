import { replaceConnections } from "@/lib/connectionsStore";
import { isVerifiedConnection, selectConnection } from "@/lib/connectionSelection.mjs";
import {
  authorizeManagedConnector,
  authorizeOAuth,
  disconnectPythonConnection,
  getManagedConnectorStatus,
  listPythonTools,
  pythonRuntimeEnabled,
  reconnectPythonConnection,
  reserveAuthorizationWindow,
  testPythonConnection,
} from "@/lib/auraApi";
import {
  CATALOG,
  catalogEntryFor,
  providerForTool,
  replaceToolCatalog,
} from "@/lib/toolCatalog";

export async function connectTool(toolName, opts = {}) {
  if (!pythonRuntimeEnabled) {
    throw new Error("AURA's secure connection service is not available right now.");
  }
  const entry = catalogEntryFor(toolName);
  if (!entry?.connectable || !entry.provider) {
    throw new Error(
      `${toolName} is not available as a verified one-click connector yet. ` +
      "Your work remains saved and no API key or MCP setup is required from you."
    );
  }

  const provider = entry.provider;
  const authorizationWindow = reserveAuthorizationWindow(provider);
  try {
    const existing = await getToolConnection(toolName, opts.connectionId);
    const managed = await getManagedConnectorStatus(true).catch(() => ({
      configured: false,
      providers: [],
    }));
    const result = existing?.kind === "oauth"
      ? await reconnectPythonConnection(existing, 120000, authorizationWindow)
      : managed.configured && managed.providers.includes(provider)
        ? await authorizeManagedConnector(provider, 120000, authorizationWindow)
        : await authorizeOAuth(provider, 120000, authorizationWindow);

    if (result.redirecting) {
      return { method: "oauth", connected: false, authorizationStarted: true, provider };
    }
    if (!result.tool?.id) throw new Error(`${toolName} access could not be verified.`);
    const verification = await testPythonConnection(result.tool.id);
    if (!isVerifiedConnection(verification)) {
      throw new Error(`AURA is still restoring ${toolName} access. Your work is preserved.`);
    }
    await hydrateConnections();
    return {
      method: result.managed ? "managed" : "oauth",
      connected: true,
      provider,
      connection: result.tool,
    };
  } catch (error) {
    if (!authorizationWindow.closed) authorizationWindow.close();
    throw error;
  }
}
export async function hydrateConnections() {
  if (!pythonRuntimeEnabled) {
    throw new Error("AURA's secure connection service is not configured.");
  }
  const status = await getManagedConnectorStatus(true).catch(() => null);
  if (status) replaceToolCatalog(status);

  const tools = await listPythonTools();
  const health = await Promise.all(tools.map(async (tool) => {
    if (!tool.enabled || tool.kind !== "oauth") return { tool, connected: Boolean(tool.enabled) };
    try {
      const result = await testPythonConnection(tool.id);
      return { tool, connected: isVerifiedConnection(result) };
    } catch {
      return { tool, connected: false };
    }
  }));

  const map = {};
  for (const { tool, connected } of health) {
    if (!connected) continue;
    if (tool.display_name) map[tool.display_name] = true;
    CATALOG.filter((entry) => entry.provider === tool.slug).forEach((entry) => {
      map[entry.name] = true;
    });
  }
  replaceConnections(map);
  return tools;
}

export async function getToolConnection(toolName, connectionId = null) {
  const tools = await listPythonTools();
  return selectConnection(tools, {
    toolName,
    provider: providerForTool(toolName),
    connectionId,
  });
}

export async function testToolConnection(toolName, connectionId = null) {
  if (!pythonRuntimeEnabled) throw new Error("Connection testing requires the secure control plane.");
  const tool = await getToolConnection(toolName, connectionId);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  return testPythonConnection(tool.id);
}

export async function disconnectTool(toolName, connectionId = null) {
  if (!pythonRuntimeEnabled) throw new Error("Revoking connections requires the secure control plane.");
  const tool = await getToolConnection(toolName, connectionId);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  await disconnectPythonConnection(tool.id);
  await hydrateConnections();
  return { disconnected: true };
}

export async function reconnectTool(toolName, connectionId = null) {
  if (!pythonRuntimeEnabled) throw new Error("Reauthorization requires the secure control plane.");
  const provider = providerForTool(toolName);
  if (!provider) throw new Error(`${toolName} is not a released one-click connector.`);
  const authorizationWindow = reserveAuthorizationWindow(provider, true);
  try {
    const tool = await getToolConnection(toolName, connectionId);
    if (!tool) throw new Error(`${toolName} is not connected.`);
    const result = await reconnectPythonConnection(tool, 120000, authorizationWindow);
    await hydrateConnections();
    return result;
  } catch (error) {
    if (!authorizationWindow.closed) authorizationWindow.close();
    throw error;
  }
}
