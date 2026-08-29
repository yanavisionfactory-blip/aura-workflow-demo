import { createClientFromRequest } from "npm:@base44/sdk@0.8.40";

// Persists an approved connection. Called after the user approves access to a
// tool — for oauth and mcp, AURA connects behind the scenes and records it
// here; for interface tools, this is called once the AURA Interface learn flow
// completes. Survives across sessions.
export default async function (req) {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });

    const body = await req.json().catch(() => ({}));
    const toolName = (body.tool || "").trim();
    const method = body.method;
    if (!toolName || !method) {
      return Response.json({ error: "tool and method are required" }, { status: 400 });
    }

    // Don't duplicate an existing connection for this user.
    const existing = await base44.asServiceRole.entities.ToolConnection.filter({
      tool_name: toolName,
      connected_by_id: user.id,
    });
    if (existing.length > 0) {
      return Response.json({ ok: true, tool: toolName, already: true });
    }

    await base44.entities.ToolConnection.create({
      tool_name: toolName,
      method,
      meta: body.meta || {},
    });

    return Response.json({ ok: true, tool: toolName });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}