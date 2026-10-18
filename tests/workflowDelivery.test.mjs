import test from "node:test";
import assert from "node:assert/strict";
import { deliveryLink, deliveryMetrics, deliverySections, parseDeliveryBundle } from "../src/lib/workflowDelivery.mjs";

const bundle = () => ({ schemaVersion: 1, title: "SEO review pack", client: "Fictional client", brief: { goal: "Prepare content", audience: "Homeowners", services: [], areas: [] },
  articles: [{ location: "Example", title: "Service guide", body: "Complete article prose. ".repeat(150), words: 450, status: "draft", verification: { at: "2026-10-18T15:00:00Z", source: "WordPress editor" }, seo: { title: "Example guide", description: "Demonstration description", focusKeyword: "example service", verifiedAt: "2026-10-18T15:00:00Z" } }],
  keywords: { rows: [{ keyword: "example service", volume: 10, competition: "LOW", index: 0 }], notes: [] },
  images: { outcome: "Optimization not executed", checkedAt: "2026-10-18T15:00:00Z" }, measurements: [], handoff: { summary: "Existing task verified", link: "https://example.atlassian.net/browse/DEMO-1" }, execution: { reused: ["Existing draft"] }, feedback: ["Is this useful?"] });

test("review delivery preserves conditional non-execution without marking a provider run complete", () => {
  const source = { ...bundle(), backend_run_id: "not-an-executed-run", status: "completed", credentials: "discard" };
  const result = parseDeliveryBundle(JSON.stringify(source));
  assert.equal(result.images.outcome, "Optimization not executed");
  assert.equal(result.status, undefined);
  assert.equal(result.backend_run_id, undefined);
  assert.equal(result.credentials, undefined);
  assert.deepEqual(deliveryMetrics(result).map((m) => m.value), [1, 1, 3]);
  assert.match(deliverySections(result).find(([title]) => title === "Image checks")[1], /not executed/);
});

test("delivery import requires full unpublished bodies and verified saved SEO fields", () => {
  const published = bundle(); published.articles[0].status = "publish";
  assert.throws(() => parseDeliveryBundle(JSON.stringify(published)), /unpublished/);
  const incomplete = bundle(); incomplete.articles[0].body = "Content will be written";
  assert.throws(() => parseDeliveryBundle(JSON.stringify(incomplete)), /full body/);
  const unverified = bundle(); delete unverified.articles[0].seo.verifiedAt;
  assert.throws(() => parseDeliveryBundle(JSON.stringify(unverified)), /readback time/);
});

test("delivery links cannot execute code or carry credentials and access tokens", () => {
  for (const value of ["javascript:alert(1)", "http://example.com", "https://user:secret@example.com", "https://example.com?access_token=secret"]) assert.equal(deliveryLink(value), null);
  assert.equal(deliveryLink("https://example.com/wp-admin/post.php?post=107&action=edit"), "https://example.com/wp-admin/post.php?post=107&action=edit");
});
