// Display saved receipts only. This module never dispatches a provider action.
const secretKey = /(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|client[_-]?secret|credential|cookie|private[_-]?key)/i;

export function redactEvidence(value, depth = 0) {
  if (depth > 30) return "[Nested response omitted]";
  if (typeof value === "string") {
    return value.replace(/data:[^\s]*;base64,[A-Za-z0-9+/=]+/g, "[Uploaded file content]")
      .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [redacted]")
      .replace(/([?&](?:api_key|key|token|access_token|client_secret)=)[^&#\s]+/gi, "$1[redacted]");
  }
  if (Array.isArray(value)) return value.map((item) => redactEvidence(item, depth + 1));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value)
    .map(([key, item]) => [key, secretKey.test(key) ? "[redacted]" : redactEvidence(item, depth + 1)]));
  return value;
}

export function readableProviderResponse(value) {
  if (value && typeof value === "object" && Array.isArray(value.content)) {
    const parts = value.content.map((part) => {
      if (part.type !== "text" || typeof part.text !== "string") return part;
      try { return JSON.parse(part.text); } catch { return part.text; }
    });
    // Retain error flags, structured content and mixed media metadata.
    return { ...value, content: parts };
  }
  return value;
}

export function evidenceToolName(value = "AURA") {
  const match = String(value).match(/^agent-(semrush|ahrefs|sitebulb|screaming-frog)-[a-f0-9]+$/i);
  if (!match) return value;
  return ({ semrush: "Semrush", ahrefs: "Ahrefs", sitebulb: "Sitebulb", "screaming-frog": "Screaming Frog" })[match[1].toLowerCase()];
}

export function toolEvidence(activity = []) {
  return activity.map((step, index) => {
    const output = step.output || {};
    const hasResponse = Object.hasOwn(output, "provider_result");
    const response = readableProviderResponse(output.provider_result);
    const providerError = output.provider_result?.isError === true;
    return {
      id: step.id || `${step.stepKey || step.key || "step"}-${index}`,
      tool: evidenceToolName(step.tool),
      action: step.action || step.reason || "Provider action",
      operation: output.operation || step.operation || "",
      status: providerError ? "provider_error" : step.status || "pending",
      hasResponse,
      response: hasResponse ? redactEvidence(response) : null,
      inputs: redactEvidence(output.resolved_arguments ?? step.arguments ?? null),
      error: redactEvidence(step.error || output.error || ""),
      startedAt: step.started_at || null,
      completedAt: step.completed_at || null,
    };
  });
}
