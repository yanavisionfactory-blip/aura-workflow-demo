import test from "node:test";
import assert from "node:assert/strict";
import { attachDocument, getAttachedDocuments, removeDocument, replaceAttachedDocuments } from "../src/lib/documentStore.js";

test("identical exported bytes retain distinct source filenames and can be removed individually", () => {
  const file_url = "data:text/csv;base64,QWRkcmVzcyxTdGF0dXMK";
  attachDocument({ name: "internal_all.csv", file_url });
  attachDocument({ name: "allinlinks.csv", file_url });
  attachDocument({ name: "internal_all.csv", file_url });
  assert.deepEqual(getAttachedDocuments().map((item) => item.name).sort(), ["allinlinks.csv", "internal_all.csv"]);
  removeDocument(file_url, "internal_all.csv");
  assert.deepEqual(getAttachedDocuments().map((item) => item.name), ["allinlinks.csv"]);
  removeDocument(file_url, "allinlinks.csv");
  assert.deepEqual(getAttachedDocuments(), []);
});

test("repeating a saved run replaces unrelated uploads without copying execution state", () => {
  attachDocument({ name: "unrelated.txt", file_url: "data:text/plain;base64,YQ==" });
  const source = { name: "original.mp4", file_url: "data:video/mp4;base64,YWI=", size: 2, approved: true };
  replaceAttachedDocuments([source]);
  assert.deepEqual(getAttachedDocuments(), [{ name: source.name, file_url: source.file_url, size: 2 }]);
  assert.notEqual(getAttachedDocuments()[0], source);
  replaceAttachedDocuments([]);
  assert.deepEqual(getAttachedDocuments(), []);
});

test("a large restored upload clears stale cached documents when storage is full", () => {
  let removed;
  globalThis.window = { sessionStorage: {
    setItem() { throw new Error("QuotaExceededError"); },
    removeItem(key) { removed = key; },
  } };
  try {
    const source = { name: "video.mp4", file_url: "data:video/mp4;base64,YWI=", size: 2 };
    replaceAttachedDocuments([source]);
    assert.equal(removed, "aura_attached_documents");
    assert.deepEqual(getAttachedDocuments(), [source]);
  } finally { delete globalThis.window; replaceAttachedDocuments([]); }
});
