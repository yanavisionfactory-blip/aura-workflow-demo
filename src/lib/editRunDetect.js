// Detects whether an edit introduces a NEW consequential (modify) action
// that wasn't present in the original run. Returns { message, action, tool }
// or null.

function sig(step) {
  return [step?.tool, step?.action].filter(Boolean).join("|").toLowerCase().trim();
}

export function detectNewConsequential(originalSteps = [], editedSteps = []) {
  const origModifySigs = new Set(
    (originalSteps || []).filter((s) => s.riskLevel === "modify").map(sig)
  );
  const fresh = (editedSteps || []).filter(
    (s) => s.riskLevel === "modify" && !origModifySigs.has(sig(s))
  );
  if (fresh.length === 0) return null;

  const step = fresh[0];
  const text = `${step.tool || ""} ${step.action || ""}`.toLowerCase();
  let message;

  if (/send/.test(text) && /mail|email|gmail|outlook/.test(text)) {
    message = "This change will send emails. AURA will ask for your approval before sending.";
  } else if (/post|message/.test(text) && /slack|channel|message/.test(text)) {
    message = "This change will post messages. AURA will ask for your approval before posting.";
  } else if (/create|add|log/.test(text) && /task|ticket|jira|issue|linear/.test(text)) {
    message = "This change will create tasks. AURA will ask for your approval before creating them.";
  } else if (/update|sync|write|push|upsert/.test(text) && /crm|hubspot|salesforce|record|sheet|sheets|notion|database|airtable/.test(text)) {
    message = "This change will update records. AURA will ask for your approval before updating them.";
  } else if (/schedule|book/.test(text) && /calendar|event|meeting/.test(text)) {
    message = "This change will schedule events. AURA will ask for your approval before scheduling.";
  } else {
    message = `This change adds a step that sends or changes data: ${step.action || "an action"}. AURA will ask for your approval before running it.`;
  }

  return { message, action: step.action || "", tool: step.tool || "" };
}