import test from "node:test";
import assert from "node:assert/strict";
import { nativeToolView } from "../src/lib/nativeToolView.mjs";
import { primaryResultFromOutputs } from "../src/lib/resultPresentation.mjs";

const google = { tool: "Google Ads", operation: "google-ads.create-campaign-report", status: "completed", hasResponse: true,
  inputs: { accountId: "9999999999", customerClientId: "1234567890" },
  response: { ret: { results: [{ campaign: { name: "Test campaign" }, metrics: { clicks: "1" } }] } } };
const meta = (id) => ({ tool: "Meta Ads", operation: "meta-ads.insights.read", status: "completed", hasResponse: true,
  response: { account_id: `act_${id}`, data: [] } });

test("Google uses the reporting customer and never fabricates an opaque UI account ID", () => {
  const manager = { ...google, response: { ret: [{ customer: { id: "9999999999", descriptiveName: "Manager" } }] }, inputs: {} };
  const model = nativeToolView("Google Ads", [google, manager]);
  assert.deepEqual(model.accounts, ["1234567890"]);
  assert.equal(model.targets[0].link, "https://ads.google.com/aw/campaigns");
  assert.match(model.note, /last-used account/);
});
test("Meta links each verified source account and does not use malformed IDs", () => {
  const model = nativeToolView("Meta Ads", [meta("1234"), meta("5678"), meta("1234"), meta("oops&act=999")]);
  assert.deepEqual(model.accounts, ["1234", "5678"]);
  assert.deepEqual(model.targets.map((t) => t.link), ["1234", "5678"].map((id) => `https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=${id}`));
});
test("failed and supplied-export results do not claim native account access", () => {
  for (const entry of [{ ...google, status: "failed" }, { ...google, synthetic: true }, { ...google, source: { rows: [] } }]) {
    assert.equal(nativeToolView("Google Ads", [entry]), null);
  }
  assert.match(nativeToolView("Google Ads", [{ ...google, inputs: {} }]).note, /No customer account ID/);
});
test("Canva preserves the provider's opaque private design URL without inventing an embed", () => {
  const link = "https://www.canva.com/api/design/signed-test-token/edit?source=receipt";
  const model = nativeToolView("Canva", [], { kind: "presentation", designId: "DA-TEST", title: "Report", link });
  assert.equal(model.targets[0].link, link);
  assert.equal(model.embedUrl, null);
  assert.match(model.note, /actual design/);
});
test("Canva embeds require an explicit matching design URL on the provider domain", () => {
  const result = { kind: "presentation", designId: "DA-TEST", link: "https://www.canva.com/design/DA-TEST/edit" };
  for (const embedUrl of [result.link, "https://www.canva.com/design/OTHER/view?embed", "https://www.canva.com.attacker.invalid/design/DA-TEST/view?embed", "https://user:secret@www.canva.com/design/DA-TEST/view?embed"]) {
    assert.equal(nativeToolView("Canva", [], { ...result, embedUrl }).embedUrl, null);
  }
  const embedUrl = "https://www.canva.com/design/DA-TEST/share-token/view?embed";
  assert.equal(nativeToolView("Canva", [], { ...result, embedUrl }).embedUrl, embedUrl);
  assert.equal(nativeToolView("Canva", [], { ...result, link: "https://attacker.invalid/design/DA-TEST/edit" }).targets.length, 0);
});
test("Canva view and embed metadata comes from the exact saved design receipt", () => {
  const urls = { edit_url: "https://www.canva.com/api/design/test-token/edit", view_url: "https://www.canva.com/api/design/test-token/view", embed_url: "https://www.canva.com/design/DA-TEST/view?embed" };
  const result = primaryResultFromOutputs([{ operation: "canva.design.get", provider_result: { design: { id: "DA-TEST", title: "Test report", urls } }, critic: { action: "accept" }, outcome_check: { status: "verified" } }]);
  assert.equal(result.viewLink, urls.view_url);
  assert.equal(result.embedUrl, urls.embed_url);
});
