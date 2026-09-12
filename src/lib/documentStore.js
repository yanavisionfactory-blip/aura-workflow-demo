const STORAGE_KEY = "aura_attached_documents";
const listeners = new Set();

function load() {
  if (typeof window === "undefined") return [];
  try {
    const value = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(value) ? value.filter((item) => item?.name && item?.file_url) : [];
  } catch {
    return [];
  }
}

let documents = load();

function publish() {
  if (typeof window !== "undefined") {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(documents));
    } catch {
      // Large file data stays available in memory for this page even when the
      // browser declines to cache it in session storage.
    }
  }
  listeners.forEach((listener) => listener([...documents]));
}

export function getAttachedDocuments() {
  return [...documents];
}

export function attachDocument(document) {
  if (!document?.file_url) return;
  documents = [
    ...documents.filter((item) => item.file_url !== document.file_url),
    document,
  ];
  publish();
}

export function removeDocument(fileUrl) {
  documents = documents.filter((item) => item.file_url !== fileUrl);
  publish();
}

export function subscribeDocuments(listener) {
  listeners.add(listener);
  listener(getAttachedDocuments());
  return () => listeners.delete(listener);
}

