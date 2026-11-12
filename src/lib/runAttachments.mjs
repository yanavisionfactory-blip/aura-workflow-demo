// Restore the original upload bytes as run inputs, never as prompt text.
export function attachedDocumentsFromRun(run = {}) {
  const documents = run.inputs?.attached_documents ?? run.inputs?.documents;
  if (!Array.isArray(documents)) return [];
  return documents.filter((document) => document && typeof document.name === "string"
    && typeof document.file_url === "string" && document.file_url.startsWith("data:"))
    .map(({ name, file_url, size }) => ({ name, file_url, size }));
}

// Offer a new upload review only for the known local Frame.io target failure.
// Never reinterpret a provider timeout, authorization failure, write or receipt.
export function frameioTargetRecovery(run = {}) {
  if (!["waiting_for_action", "blocked", "failed"].includes(run.status)
      || !run.plan_approved || !String(run.prompt || "").trim()) return null;
  if (run.blocker && !["choose_resource", "inspect_run"].includes(run.blocker.action)) return null;
  const steps = run.steps || [];
  const failed = steps.filter((step) => step.status === "failed");
  if (failed.length !== 1 || steps.some((step) => step.consequential !== false
      || !["frameio.identity.get", "frameio.video.review"].includes(step.operation))) return null;
  const step = failed[0];
  if (step.operation !== "frameio.video.review" || step.output?.provider_result
      || !(step.recovery?.reason_code === "frameio_target_invalid"
        || ["Select the exact Frame.io file UUID.", "Select the exact Frame.io account UUID.",
        "frameio.video.review.file_id has an invalid format", "frameio.video.review.account_id has an invalid format"]
          .some((message) => String(step.error || "").includes(message)))) return null;
  if (steps.some((item) => item.operation === "frameio.video.review" && item.status === "completed")) return null;
  return { stepId: step.id, index: steps.indexOf(step) };
}

export function uploadedVideoRecovery(run = {}) {
  const target = frameioTargetRecovery(run);
  if (!target) return null;
  const documents = attachedDocumentsFromRun(run);
  if (documents.length !== 1) return null;
  const document = documents[0];
  const type = document.file_url.slice(5).split(/[;,]/, 1)[0].toLowerCase();
  if (!["video/mp4", "video/quicktime"].includes(type)
      && !(type === "application/octet-stream" && /\.(mp4|mov)$/i.test(document.name))) return null;
  return { document, ...target };
}
