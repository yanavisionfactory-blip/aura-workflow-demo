import test from "node:test";
import assert from "node:assert/strict";
import { formatLocalTime, parseLocalTime } from "../src/lib/pilotTime.mjs";

test("the pilot preserves the chosen wall-clock time when creating an offset timestamp", () => {
  const chosen = "2026-09-24 12:30";
  const date = parseLocalTime(chosen);
  assert.ok(date);
  assert.equal(formatLocalTime(date), chosen);
  assert.equal(date.getHours(), 12);
  assert.equal(date.getMinutes(), 30);
  assert.match(date.toISOString(), /^2026-09-2[345]T/);
});

test("the pilot rejects rollover dates and incomplete local times", () => {
  for (const invalid of ["2026-02-31 12:30", "2026-09-24 25:30", "2026-09-24T12:30", "tomorrow"]) {
    assert.equal(parseLocalTime(invalid), null);
  }
});
