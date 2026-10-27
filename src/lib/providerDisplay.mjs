// The connector owns execution; the visible provider follows the actual action.
// Other AURA utilities are not ChatGPT calls.
export function operationProviderName(name, operation = "") {
  if (operation === "intelligence.claude_backup") return "AURA Intelligence";
  if (["web.page.read", "web.search"].includes(operation)) return "Web research";
  return operation === "report.compose" ? "ChatGPT" : name;
}

export function intelligenceBackupNotice(step = {}) {
  const receipt = step.output?.fallback || step.fallback;
  if (receipt?.actual_tool !== "aura" || receipt.actual_operation !== "intelligence.claude_backup") return "";
  return typeof receipt.message === "string" ? receipt.message : "";
}

export function intelligenceBackupNotices(activity = []) {
  return [...new Set(activity.map(intelligenceBackupNotice).filter(Boolean))];
}
