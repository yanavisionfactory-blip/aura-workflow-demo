const MAX_DOCUMENTS = 8;
const MAX_FILE_BYTES = 10 * 1024 * 1024;
// RunCreate counts encoded data URLs, including their MIME headers.
const MAX_ENCODED_BYTES = 16_000_000;

export function uploadBatchError(files, documents = []) {
  if (files.length + documents.length > MAX_DOCUMENTS) {
    return "Attach no more than eight files to one workflow.";
  }
  if (files.some((file) => file.size > MAX_FILE_BYTES)) {
    return "Each file must be 10 MB or smaller.";
  }
  const existing = documents.reduce((total, doc) => total + (doc.file_url?.length || 0), 0);
  const incoming = files.reduce((total, file) => total + 4 * Math.ceil(file.size / 3)
    + `data:${file.type || "application/octet-stream"};base64,`.length, 0);
  if (existing + incoming > MAX_ENCODED_BYTES) {
    return "These files exceed this workflow’s combined upload limit. Attach fewer or smaller files.";
  }
  return "";
}
