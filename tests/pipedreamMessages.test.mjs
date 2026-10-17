import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const clients = [
  ["ESM", await import("@pipedream/sdk/browser")],
  ["CommonJS", require("@pipedream/sdk/browser")],
];

async function connectionFixture(createFrontendClient) {
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  const listeners = new Set();
  const frames = [];
  const calls = [];
  globalThis.window = {
    addEventListener(type, listener) {
      assert.equal(type, "message");
      listeners.add(listener);
    },
    removeEventListener(type, listener) {
      assert.equal(type, "message");
      listeners.delete(listener);
    },
  };
  globalThis.document = {
    createElement(tag) {
      assert.equal(tag, "iframe");
      const frame = {
        style: {},
        contentWindow: {},
        remove() {
          const index = frames.indexOf(frame);
          if (index !== -1) frames.splice(index, 1);
          frame.contentWindow = null;
        },
      };
      return frame;
    },
    body: {
      appendChild(frame) {
        frames.push(frame);
        frame.onload?.();
      },
    },
  };
  const client = createFrontendClient({
    externalUserId: "test-user",
    projectEnvironment: "development",
    token: "test-connect-grant",
    tokenCallback: async () => ({
      token: "test-connect-grant",
      expiresAt: new Date(Date.now() + 60000),
      connectLinkUrl: "",
    }),
  });
  await client.connectAccount({
    app: "google_ads",
    token: "test-connect-grant",
    onSuccess: (value) => calls.push(["success", value]),
    onError: (error) => calls.push(["error", error.message]),
    onClose: (value) => calls.push(["close", value]),
  });
  const source = frames[0].contentWindow;
  return {
    calls,
    frames,
    listeners,
    source,
    send(data, { origin = "https://pipedream.com", sender = source } = {}) {
      for (const listener of [...listeners]) {
        listener({ data, origin, source: sender });
      }
    },
    restore() {
      globalThis.window = previousWindow;
      globalThis.document = previousDocument;
    },
  };
}

for (const [format, { createFrontendClient }] of clients) {
  test(`${format}: preserves the provider's current message field`, async () => {
    const fixture = await connectionFixture(createFrontendClient);
    try {
      const message = "Sign in to Pipedream to connect in development mode.";
      fixture.send({ type: "error", message });
      assert.deepEqual(fixture.calls, [["error", message]]);
      assert.equal(fixture.frames.length, 0);
      assert.equal(fixture.listeners.size, 0);
    } finally {
      fixture.restore();
    }
  });

  test(`${format}: ignores unrelated frames and origins for every result type`, async () => {
    const fixture = await connectionFixture(createFrontendClient);
    try {
      for (const type of ["error", "success", "close"]) {
        const data = { type, message: "Unrelated error", authProvisionId: "apn_untrusted" };
        fixture.send(data, { origin: "https://example.invalid" });
        fixture.send(data, { sender: {} });
      }
      assert.deepEqual(fixture.calls, []);
      assert.equal(fixture.frames.length, 1);
      assert.equal(fixture.listeners.size, 1);
      fixture.send({ type: "success", authProvisionId: "apn_verified" });
      assert.deepEqual(fixture.calls, [["success", { id: "apn_verified" }]]);
      assert.equal(fixture.frames.length, 0);
      assert.equal(fixture.listeners.size, 0);
      fixture.send({ type: "error", message: "Late message" });
      assert.equal(fixture.calls.length, 1);
    } finally {
      fixture.restore();
    }
  });

  test(`${format}: accepts the provider's legacy error field`, async () => {
    const fixture = await connectionFixture(createFrontendClient);
    try {
      fixture.send({ type: "error", error: "Legacy provider error" });
      assert.deepEqual(fixture.calls, [["error", "Legacy provider error"]]);
    } finally {
      fixture.restore();
    }
  });

  test(`${format}: preserves an explicit close without pretending consent succeeded`, async () => {
    const fixture = await connectionFixture(createFrontendClient);
    try {
      fixture.send({ type: "close" });
      assert.deepEqual(fixture.calls, [["close", { successful: false, completed: false }]]);
      assert.equal(fixture.frames.length, 0);
      assert.equal(fixture.listeners.size, 0);
    } finally {
      fixture.restore();
    }
  });
}
