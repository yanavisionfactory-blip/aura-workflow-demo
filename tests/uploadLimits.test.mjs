import assert from "node:assert/strict";
import test from "node:test";
import { uploadBatchError } from "../src/lib/uploadLimits.mjs";

const file = (size, type = "video/mp4") => ({ size, type });

test("the supplied short MP4 fits without a provider connection", () => {
  assert.equal(uploadBatchError([file(3824025)]), "");
});

test("individual files can fit while their encoded batch exceeds the API limit", () => {
  assert.match(uploadBatchError([file(7 * 1024 * 1024), file(7 * 1024 * 1024)]), /combined upload limit/);
  assert.equal(uploadBatchError([file(6 * 1024 * 1024), file(5 * 1024 * 1024)]), "");
});

test("existing bytes, base64 padding and MIME headers count at the boundary", () => {
  const existing = [{ file_url: "x".repeat(16_000_000 - 27) }];
  assert.equal(uploadBatchError([file(3)], existing), "");
  assert.match(uploadBatchError([file(4)], existing), /combined upload limit/);
  assert.match(uploadBatchError([file(3, "")], existing), /combined upload limit/);
});

test("count and individual size errors are actionable before upload", () => {
  assert.match(uploadBatchError(Array.from({ length: 9 }, () => file(1))), /eight files/);
  assert.match(uploadBatchError([file(10 * 1024 * 1024 + 1)]), /10 MB/);
});
