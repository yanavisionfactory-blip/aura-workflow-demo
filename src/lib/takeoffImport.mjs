// Imports are workflow inputs, never verified app connections.
export function documentInput({ name, file_url, size, source_app, source_kind }) {
  return { name, file_url, size, ...(source_app === "planswift" && source_kind === "export"
    ? { source_app, source_kind } : {}) };
}

export function inputRoutes(documents = [], selectedTools = []) {
  const nativeSelected = selectedTools.some((name) => /^plan\s*swift$/i.test(name));
  return !nativeSelected && documents.some((doc) => doc.source_app === "planswift" && doc.source_kind === "export")
    ? { planswift: "export" } : {};
}

export const TAKEOFF_IMPORT_REVISION = "Use the attached takeoff export as the source of existing measurements for this workflow. Replace live PlanSwift reads with this file. Keep the requested report and Excel output. Show a revised plan for approval; do not run the previous plan.";
