// The connector owns execution; the visible provider follows the actual action.
// Other AURA utilities are not ChatGPT calls.
export function operationProviderName(name, operation = "") {
  if (["web.page.read", "web.search"].includes(operation)) return "Web research";
  return operation === "report.compose" ? "ChatGPT" : name;
}
