// Restore the original upload bytes as run inputs, never as prompt text.
export function attachedDocumentsFromRun(run = {}) {
  const documents = run.inputs?.attached_documents ?? run.inputs?.documents;
  if (!Array.isArray(documents)) return [];
  return documents.filter((document) => document && typeof document.name === "string"
    && typeof document.file_url === "string" && document.file_url.startsWith("data:"))
    .map(({ name, file_url, size }) => ({ name, file_url, size }));
}
