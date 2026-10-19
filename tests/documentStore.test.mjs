import test from "node:test";
import assert from "node:assert/strict";
import { attachDocument, getAttachedDocuments, removeDocument } from "../src/lib/documentStore.js";

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
