export function weatherStepTitle(step = {}) {
  const requested = String(step.arguments?.date || "").trim().toLowerCase();
  const reason = String(step.reason || "").toLowerCase();
  if (requested === "today" || (!requested && /\btoday\b/.test(reason))) {
    return "Check today's weather";
  }
  if (requested === "tomorrow" || (!requested && /\btomorrow\b/.test(reason))) {
    return "Check tomorrow's weather";
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(requested)) {
    return `Check weather for ${requested}`;
  }
  return "Check the weather";
}
