import assert from "node:assert/strict";
import test from "node:test";

import { weatherStepTitle } from "../src/lib/planPresentation.mjs";

test("weather titles reflect the requested day", () => {
  assert.equal(weatherStepTitle({ arguments: { date: "today" } }), "Check today's weather");
  assert.equal(
    weatherStepTitle({ arguments: { date: "tomorrow" } }),
    "Check tomorrow's weather",
  );
  assert.equal(
    weatherStepTitle({ arguments: { date: "2026-09-20" } }),
    "Check weather for 2026-09-20",
  );
  assert.equal(
    weatherStepTitle({ reason: "Read today's Berlin forecast" }),
    "Check today's weather",
  );
  assert.equal(weatherStepTitle({}), "Check the weather");
});
