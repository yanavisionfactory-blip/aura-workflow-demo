import test from "node:test";
import assert from "node:assert/strict";
import {
  connectionScreenPreset, isSameTabAuthorizationReturn,
  redirectConnectorAuthorization, shouldNotifyAuthorizationOpener, usesSameTabAuthorization,
} from "../src/lib/connectionNavigation.mjs";

const provider = "agent-meta-ads-0123456789";
const session = {
  backend: "native", provider,
  authorization_url: "https://pipeboard.co/oauth/authorize?platform=meta-ads&state=server-only-state",
};
const callback = `?oauth_provider=${provider}&oauth_status=success`;

function browserStub() {
  const storage = new Map();
  const destinations = [];
  return {
    storage, destinations, opener: null,
    // Reproduces Safari blocking every popup; this method must never be used.
    open() { throw new Error("Popup blocked"); },
    location: { origin: "https://aura.example", assign(url) { destinations.push(url); } },
    sessionStorage: { setItem(key, value) { storage.set(key, value); }, getItem(key) { return storage.get(key); } },
  };
}

test("Meta Ads first connection and existing account reauthorization use the same tab", () => {
  for (const route of ["meta-ads-mcp", provider]) assert.equal(usesSameTabAuthorization(route), true);
  assert.equal(usesSameTabAuthorization("legacy-route", { canonical_provider: "meta-ads" }), true);
  for (const route of ["google-analytics", "google-ads", "facebook-pages", "agent-other-0123456789", undefined]) {
    assert.equal(usesSameTabAuthorization(route), false);
  }
});

test("blocked popups do not prevent navigation and starting consent never reports connected", () => {
  const browser = browserStub();
  assert.deepEqual(redirectConnectorAuthorization(session, browser), { redirecting: true, connected: false });
  assert.deepEqual(browser.destinations, [session.authorization_url]);
  assert.doesNotMatch(JSON.stringify([...browser.storage]), /server-only-state|authorization_url|token/);
  assert.equal(isSameTabAuthorizationReturn(callback, browser), true);
});

test("only a secure broker destination is navigated to", () => {
  for (const url of ["javascript:alert(1)", "http://pipeboard.co/oauth/authorize", "https://user:pass@pipeboard.co/", "/redirect"]) {
    const browser = browserStub();
    assert.throws(() => redirectConnectorAuthorization({ ...session, authorization_url: url }, browser));
    assert.deepEqual(browser.destinations, []);
  }
  assert.throws(() => redirectConnectorAuthorization({ ...session, backend: "nango" }, browserStub()));
});

test("same-tab callbacks stay open even when AURA was opened from another window", () => {
  const browser = browserStub();
  browser.opener = { location: { origin: browser.location.origin } };
  redirectConnectorAuthorization(session, browser);
  assert.equal(shouldNotifyAuthorizationOpener(callback, browser), false);
  assert.equal(isSameTabAuthorizationReturn("?oauth_provider=mcp-agent&oauth_status=error", browser), true);
  assert.equal(isSameTabAuthorizationReturn("?oauth_provider=google&oauth_status=success", browser), false);
  assert.equal(shouldNotifyAuthorizationOpener("?oauth_provider=google&oauth_status=success", browser), true);
});

test("consent still opens without session storage and cross-origin chat openers are never closed", () => {
  const browser = browserStub();
  browser.sessionStorage = { setItem() { throw new Error("disabled"); }, getItem() { throw new Error("disabled"); } };
  redirectConnectorAuthorization(session, browser);
  assert.equal(isSameTabAuthorizationReturn(callback, browser), true);
  browser.opener = { get location() { throw new Error("cross-origin"); } };
  assert.equal(shouldNotifyAuthorizationOpener(callback, browser), false);
  assert.equal(connectionScreenPreset(callback, browser).query, "Meta Ads");
  assert.equal(browser.destinations.length, 1);
});

test("deep links select Meta Ads without trusting success, arbitrary destinations, or workspace parameters", () => {
  const browser = browserStub();
  const preset = connectionScreenPreset("?connect=meta-ads&workspace=other&authorization_url=https://evil.example", browser);
  assert.equal(preset.query, "Meta Ads");
  assert.deepEqual(browser.destinations, []);
  assert.equal(connectionScreenPreset("?connect=https://evil.example", browser), null);
  const forged = connectionScreenPreset(`${callback}&oauth_message=Connected`, browser);
  assert.equal(forged.connected, undefined);
  assert.match(forged.message, /Check your verified connection status/);
  assert.equal(connectionScreenPreset("?oauth_provider=unrelated&oauth_status=success", browser), null);
});

test("denial and expired consent have retry guidance and no connected claim", () => {
  const browser = browserStub();
  redirectConnectorAuthorization(session, browser);
  for (const query of [`?oauth_provider=${provider}&oauth_status=error`, "?oauth_provider=mcp-agent&oauth_status=error"]) {
    const preset = connectionScreenPreset(query, browser);
    assert.match(preset.message, /Tap Connect to try again/);
    assert.equal(preset.connected, undefined);
  }
});
