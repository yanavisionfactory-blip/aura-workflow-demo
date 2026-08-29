import { createClientFromRequest } from "npm:@base44/sdk@0.8.40";
import { TOOL_REGISTRY } from "../../shared/toolRegistry.ts";

// AURA's connection intelligence. Given a tool name, decides the best
// connection method (oauth / mcp / interface) and reports whether it is
// already connected. For tools not in the registry, the LLM classifies the
// method — the "agent decides" happens here, behind the scenes.
export default async function (req) {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });

    const body = await req.json().catch(() => ({}));
    const toolName = (body.tool || "").trim();
    if (!toolName) {
      return Response.json({ error: "tool is required" }, { status: 400 });
    }

    let entry = TOOL_REGISTRY[toolName] || null;
    let decidedByAgent = false;

    // Unknown tool — let the agent decide the best connection method.
    if (!entry) {
      decidedByAgent = true;
      const res = await base44.asServiceRole.integrations.Core.InvokeLLM({
        prompt: `You are AURA's connection intelligence. Decide the best method to connect to a tool named "${toolName}".

Return JSON with:
- "method": "oauth" | "mcp" | "interface"
- "connector": the likely connector slug (e.g. "gmail", "slack", "salesforce", "hubspot", "notion", "googlesheets", "jira", "googlecalendar") if method is oauth, else null
- "mcpServerUrl": a plausible MCP server URL if method is mcp, else null
- "reason": one short sentence explaining the choice

Rules:
- "oauth": the tool is a well-known SaaS app with a standard OAuth API.
- "mcp": the tool is an internal system that exposes an MCP server AURA can call directly.
- "interface": the tool is an internal or custom web app with no API — AURA will learn its web interface.
Default to "interface" for internal or clearly custom tools.`,
        response_json_schema: {
          type: "object",
          properties: {
            method: { type: "string", enum: ["oauth", "mcp", "interface"] },
            connector: { type: ["string", "null"] },
            mcpServerUrl: { type: ["string", "null"] },
            reason: { type: "string" },
          },
        },
      });
      entry = {
        method: res.method,
        connector: res.connector || undefined,
        mcpServerUrl: res.mcpServerUrl || undefined,
        reason: res.reason,
      };
    }

    // Determine whether the tool is already connected.
    // Prefer the per-user connection (each app user connects their own account);
    // fall back to the shared (builder) connection when no per-user connector
    // is registered yet. Only a real token counts — never fake a connection.
    // Shared OAuth only — the builder authorizes the connector once (no
    // client secrets, no per-user setup). A real token = connected.
    let oauthAuthorized = false;
    if (entry.method === "oauth" && entry.connector) {
      try {
        await base44.asServiceRole.connectors.getConnection(entry.connector);
        oauthAuthorized = true;
      } catch {
        oauthAuthorized = false;
      }
    }
    let connected = oauthAuthorized;
    if (!connected) {
      // Also check the persisted ToolConnection entity (interface/mcp custom
      // integrations, or a user-approved oauth record).
      const existing = await base44.asServiceRole.entities.ToolConnection.filter({
        tool_name: toolName,
        connected_by_id: user.id,
      });
      connected = existing.length > 0;
    }

    return Response.json({
      tool: toolName,
      method: entry.method,
      connector: entry.connector || null,
      mcpServerUrl: entry.mcpServerUrl || null,
      reason: entry.reason || null,
      decidedByAgent,
      oauthAuthorized,
      connected,
    });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}