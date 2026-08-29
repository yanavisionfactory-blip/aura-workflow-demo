import { createClientFromRequest } from "npm:@base44/sdk@0.8.40";
import { TOOL_REGISTRY } from "../../shared/toolRegistry.ts";

// Returns the real connection map: { toolName: true } for every connected tool.
// Merges live OAuth connector status (gmail, airtable, …) with persisted
// user-approved / interface / mcp connections from the ToolConnection entity.
export default async function (req) {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });

    const connections = {};

    // Live OAuth connector status for tools the registry maps to oauth.
    for (const [name, entry] of Object.entries(TOOL_REGISTRY)) {
      if (entry.method === "oauth" && entry.connector) {
        try {
          await base44.asServiceRole.connectors.getConnection(entry.connector);
          connections[name] = true;
        } catch {
          // not connected via the connector — may still be user-approved below
        }
      }
    }

    // Persisted connections — only interface/mcp custom integrations count.
    // OAuth tools are connected solely via the real connector status above; a
    // persisted oauth record without a live token can't actually be used.
    const records = await base44.asServiceRole.entities.ToolConnection.filter({
      connected_by_id: user.id,
    });
    for (const r of records) {
      if (r.method && r.method !== "oauth") connections[r.tool_name] = true;
    }

    return Response.json({ connections });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}