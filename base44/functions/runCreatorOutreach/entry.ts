import { createClientFromRequest } from "npm:@base44/sdk@0.8.40";
import { secrets } from "base44:runtime";
import { runCreatorOutreachCore } from "../../shared/creatorOutreach.ts";

// Recurring creator-outreach job (scheduled). The actual logic lives in the
// shared core so the AURA plan/approve/results flow runs the exact same code.

export default async function (req) {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });
    if (user.role !== "admin") return Response.json({ error: "Forbidden" }, { status: 403 });

    const body = await req.json().catch(() => ({}));
    const result = await runCreatorOutreachCore(base44, secrets, {
      niche: body.niche,
      maxCreators: body.maxCreators,
      dryRun: body.dryRun,
    });
    return Response.json(result);
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}