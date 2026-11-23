import assert from "node:assert/strict";
import test from "node:test";
import { salesforceLoginHost } from "../src/lib/salesforceLogin.mjs";

test("accepts company Salesforce pages and passes only the login hostname", () => {
  assert.equal(salesforceLoginHost("https://first.lightning.force.com/lightning/o/Contact/list?filterName=AllContacts"), "first.my.salesforce.com");
  assert.equal(salesforceLoginHost("second.my.salesforce.com"), "second.my.salesforce.com");
  assert.equal(salesforceLoginHost("first--qa.sandbox.lightning.force.com"), "first--qa.sandbox.my.salesforce.com");
});

test("rejects non-Salesforce origins, embedded credentials, and non-HTTPS links", () => {
  for (const value of ["", "account@example.org", "https://first.my.salesforce.com.example.org", "https://user@first.my.salesforce.com", "http://first.my.salesforce.com", "https://first.my.salesforce.com:8443"]) {
    assert.equal(salesforceLoginHost(value), null);
  }
});
