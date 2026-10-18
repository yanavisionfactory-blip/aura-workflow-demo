import { deliveryLink } from "./workflowDelivery.mjs";

export function parseCampaignDelivery(data) {
  if (data?.kind !== "campaign_launch" || data.schemaVersion !== 2 || data.demo !== true) throw new Error("Choose a supported campaign demonstration results file.");
  if (!data.title || !data.client || !data.summary || !data.brief?.goal) throw new Error("Include the campaign title, client and completed demonstration brief.");
  if (data.publicationStatus !== "unpublished" || !Array.isArray(data.channels) || !data.channels.length) throw new Error("Campaign review packs must contain unpublished channel drafts.");
  if (data.channels.some((c) => !c.name || !Array.isArray(c.drafts) || !c.drafts.length || c.drafts.some((d) => !d.title || !Array.isArray(d.fields) || !d.fields.length || d.fields.some((f) => !f.label || typeof f.text !== "string")))) throw new Error("Include complete, readable copy for every channel draft.");
  if (!Array.isArray(data.approvals) || data.approvals.some((a) => !a.item || !["Pending", "Needs input", "Not applicable"].includes(a.status))) throw new Error("Record unresolved approvals accurately; this file cannot grant approval.");
  if (!Array.isArray(data.assets) || !Array.isArray(data.manualSteps) || !Array.isArray(data.consistency) || !Array.isArray(data.questions) || !data.execution || typeof data.execution !== "object" || Array.isArray(data.execution)) throw new Error("Include the asset checklist, consistency review and implementation handoff.");
  if (Object.values(data.brief).some((v) => typeof v !== "string" && !(Array.isArray(v) && v.every((s) => typeof s === "string"))) || data.assets.some((a) => !a?.id || !a.name || !a.status || !a.requirement) || [...data.manualSteps, ...data.consistency, ...(data.questions || [])].some((s) => typeof s !== "string")) throw new Error("Use readable text for the brief, checklist and review actions.");
  if (data.links?.some((l) => !l.label || !deliveryLink(l.url))) throw new Error("Use verified, safe links to the existing outputs.");
  return Object.fromEntries(["kind", "schemaVersion", "demo", "title", "agency", "client", "summary", "preparedAt", "publicationStatus", "brief", "channels", "assets", "approvals", "manualSteps", "consistency", "links", "execution", "questions"].map((k) => [k, data[k]]));
}
