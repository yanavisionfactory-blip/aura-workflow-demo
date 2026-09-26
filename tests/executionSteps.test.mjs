import test from "node:test";
import assert from "node:assert/strict";

import { alignExecutionSteps } from "../src/lib/executionSteps.mjs";

test("execution keeps the reviewed order and labels even if runtime rows arrive out of order", () => {
  const reviewed = [
    { key: "find", title: "Find customer messages", tool: "Gmail" },
    { key: "read", title: "Read relevant threads", tool: "Gmail" },
  ];
  const runtime = [
    { key: "read", status: "completed" },
    { key: "internal", status: "completed" },
    { key: "find", status: "completed" },
  ];
  const aligned = alignExecutionSteps(reviewed, runtime);
  assert.deepEqual(aligned.map(({ planned }) => planned.title), reviewed.map((step) => step.title));
  assert.deepEqual(aligned.map(({ runtime: step }) => step.key), ["find", "read"]);
  assert.equal(alignExecutionSteps(reviewed, [runtime[0]])[0].runtime, undefined);
});
