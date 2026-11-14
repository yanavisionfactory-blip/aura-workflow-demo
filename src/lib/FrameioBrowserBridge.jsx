import { useEffect } from "react";
import { useAuth } from "@/lib/AuthContext";
import { auraRequest, approvePythonPlan, createPythonRun, getPythonRun } from "@/lib/auraApi";
import { registerFrameioBrowserTools } from "@/lib/frameioBrowserTools.mjs";

export default function FrameioBrowserBridge() {
  const { workspace } = useAuth();
  useEffect(() => {
    if (!workspace?.workspace_id) return undefined;
    return registerFrameioBrowserTools(document.modelContext || navigator.modelContext, {
      request: auraRequest, approveRun: approvePythonPlan, createRun: createPythonRun, getRun: getPythonRun,
    });
  }, [workspace?.workspace_id]);
  return null;
}
