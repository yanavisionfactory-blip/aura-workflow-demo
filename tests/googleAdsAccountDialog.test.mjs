import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { googleAdsAccountDialog } from "../src/lib/googleAdsAccountDialog.js";

const root = "1234567890", customer = "9876543210";
const chosen = { login_customer_id: root, customer_id: customer, name: "Client Advertising" };
const directory = { access_accounts: [{ id: root, name: "Agency" }], login_customer_id: root,
  accounts: [chosen], selected_account: null };
let dom;
function setup() {
  dom = new JSDOM("<!doctype html><body></body>");
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  dom.window.HTMLDialogElement.prototype.close = function () { this.open = false; };
}
afterEach(() => { dom?.window.close(); delete globalThis.window; delete globalThis.document; });
const tick = () => new Promise((resolve) => setImmediate(resolve));
const event = (name) => new window.Event(name, { bubbles: true, cancelable: true });
const form = () => document.querySelector("form");

test("Reddit uses business and ad-account choices without developer credentials", async () => {
  setup();
  const business = "1e200a0b-4e98-32cc-dd47-3006e4c85bb2";
  const account = { login_customer_id: business, customer_id: "t2_advertiser", name: "Reddit campaign account" };
  let saved;
  const result = googleAdsAccountDialog({ platform: "Reddit", load: async () => ({
    access_accounts: [{ id: business, name: "Customer business" }], login_customer_id: business,
    accounts: [account],
  }), save: async (value) => { saved = value; return { selected_account: account }; } });
  await tick();
  assert.match(document.querySelector("h2").textContent, /Reddit Ads/);
  assert.doesNotMatch(document.body.textContent, /Google|client.secret|client.id/i);
  assert.match(document.body.textContent, /shared into a business/);
  assert.deepEqual([...document.querySelectorAll("input")].map(input => input.type), ["search"]);
  form().dispatchEvent(event("submit"));
  assert.deepEqual(await result, account);
  assert.equal(saved.customer_id, "t2_advertiser");
});

test("shows named accounts without credentials or customer-number text fields, and saves the selected provider result", async () => {
  setup();
  let payload;
  const result = googleAdsAccountDialog({ load: async () => directory,
    save: async (value) => { payload = value; return { selected_account: chosen }; } });
  await tick();
  assert.match(form().elements.account.textContent, /Client Advertising/);
  assert.equal(form().elements.account.value, customer);
  assert.deepEqual([...document.querySelectorAll("input")].map(input => input.type), ["search"]);
  form().dispatchEvent(event("submit"));
  assert.deepEqual(await result, chosen);
  assert.deepEqual(payload, { login_customer_id: root, customer_id: customer, search: "" });
  assert.equal(document.querySelector("dialog"), null);
});

test("multiple account choices require an explicit selection and render provider names only as text", async () => {
  setup();
  const hostileName = '<img src=x onerror="alert(1)">';
  const result = googleAdsAccountDialog({ load: async () => ({ ...directory,
    accounts: [chosen, { ...chosen, customer_id: "1111111111", name: hostileName }] }),
    save: async () => { throw new Error("not expected"); } });
  await tick();
  assert.equal(form().elements.account.value, "");
  assert.equal(document.querySelector('[type="submit"]').disabled, true);
  assert.match(form().elements.account.textContent, /onerror/);
  assert.equal(document.querySelector("img"), null);
  document.querySelector("[data-close]").click();
  assert.equal(await result, null);
});

test("empty accounts and temporary provider failures retain sign-in and offer retry", async () => {
  setup();
  let fail = true, calls = 0;
  const result = googleAdsAccountDialog({ load: async () => {
    calls++;
    if (fail) throw new Error("Try again");
    return { access_accounts: [], accounts: [], login_customer_id: null };
  }, save: async () => assert.fail("must not save") });
  await tick();
  assert.match(document.querySelector('[role="alert"]').textContent, /Try again/);
  assert.equal(document.querySelector('[type="submit"]').disabled, true);
  fail = false;
  document.querySelector("[data-retry]").click();
  await tick();
  assert.equal(calls, 2);
  assert.match(document.querySelector('[role="status"]').textContent, /No Google Ads accounts/);
  assert.equal(document.querySelector('[type="submit"]').disabled, true);
  document.querySelector("dialog").dispatchEvent(event("cancel"));
  await result;
});

test("late discovery responses cannot replace the currently searched account", async () => {
  setup();
  const pending = [];
  const result = googleAdsAccountDialog({ load: (login, search) => new Promise(resolve => pending.push({ search, resolve })),
    save: async () => assert.fail("must not save") });
  const search = form().elements.search;
  search.value = "New";
  search.dispatchEvent(event("input"));
  search.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  assert.equal(pending.length, 2);
  assert.equal(document.querySelector('[type="submit"]').disabled, true);
  pending[1].resolve({ ...directory, accounts: [{ ...chosen, name: "New client" }] });
  await tick();
  pending[0].resolve(directory);
  await tick();
  assert.match(form().elements.account.textContent, /New client/);
  assert.doesNotMatch(form().elements.account.textContent, /Client Advertising/);
  document.querySelector("[data-close]").click();
  await result;
});

test("choosing a different manager clears stale accounts and uses the new access route", async () => {
  setup();
  const calls = [];
  const result = googleAdsAccountDialog({ load: async (login) => {
    calls.push(login);
    return { ...directory, access_accounts: [{ id: root, name: "Agency" }, { id: customer, name: "Direct" }],
      login_customer_id: login || null, accounts: login ? [{ ...chosen, login_customer_id: login }] : [] };
  }, save: async () => assert.fail("must not save") });
  await tick();
  assert.equal(document.querySelector("[data-access]").hidden, false);
  const access = form().elements.access;
  access.value = customer;
  access.dispatchEvent(event("change"));
  assert.equal(document.querySelector('[type="submit"]').disabled, true);
  await tick();
  assert.deepEqual(calls, ["", customer]);
  assert.equal(form().elements.account.value, customer);
  document.querySelector("[data-close]").click();
  await result;
});

test("a failed save keeps the picker open without claiming a changed account", async () => {
  setup();
  const result = googleAdsAccountDialog({ load: async () => directory,
    save: async () => { throw new Error("Access was removed"); } });
  await tick();
  form().dispatchEvent(event("submit"));
  assert.equal(document.querySelector("[data-close]").disabled, true);
  await tick();
  assert.match(document.querySelector('[role="alert"]').textContent, /Access was removed/);
  assert.match(document.querySelector('[role="status"]').textContent, /has not changed/);
  assert.equal(document.querySelector("dialog").open, true);
  document.querySelector("[data-close]").click();
  await result;
});

test("Reddit refresh scans all businesses despite a saved default and shows partial coverage", async () => {
  setup();
  const calls = [];
  const result = googleAdsAccountDialog({ platform: "Reddit", selected: chosen, load: async (login) => {
    calls.push(login);
    return { access_accounts: [{ id: root, name: "Old" }, { id: customer, name: "New" }], login_customer_id: null,
      accounts: [chosen, { ...chosen, customer_id: "a2_new", name: "New advertiser" }],
      coverage: { status: "partial", warnings: ["Shared-account discovery is unavailable for Old."] } };
  }, save: async () => assert.fail("must not save automatically") });
  await tick();
  assert.deepEqual(calls, [""]);
  assert.match(form().elements.access.textContent, /All accessible businesses/);
  assert.match(form().elements.account.textContent, /New advertiser/);
  assert.equal(document.querySelector("[data-coverage]").hidden, false);
  assert.match(document.querySelector("[data-coverage]").textContent, /Shared-account discovery/);
  assert.match(document.querySelector('[role="status"]').textContent, /2 advertising accounts/);
  document.querySelector("[data-close]").click();
  await result;
});
