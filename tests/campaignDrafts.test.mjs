import assert from 'node:assert/strict';
import { test } from 'node:test';
import { campaignDraftRequest, CAMPAIGN_DRAFT_PREFIX, savedCampaignDraft } from '../src/lib/campaignDrafts.mjs';
import { primaryResultFromOutputs } from '../src/lib/resultPresentation.mjs';

const fields = { client: 'Fixture Home', brief_reference: 'Approved brief', audience_id: 'list-42',
  audience_name: 'Fixture customers', title: 'Campaign draft', subject: 'Dinnerware for your table',
  preview_text: 'Explore the collection', from_name: 'Fixture Home', reply_to: 'team@example.test',
  headline: 'Find your next place setting', body: 'Explore the collection.',
  cta_label: 'Explore dinnerware', cta_url: 'https://example.test/collection' };
const verify = { critic: { action: 'accept' }, outcome_check: { status: 'verified' } };
function outputs() {
  return [
    { ...verify, step_key: 'campaign', operation: 'mailchimp.campaign.draft.create',
      provider_result: { id: 'campaign-42', status: 'save' }, resolved_arguments: fields },
    { ...verify, step_key: 'content', operation: 'mailchimp.campaign.content.set',
      resolved_arguments: { campaign_id: 'campaign-42', expected_list_id: 'list-42',
        html: '<p>Saved content</p>', plain_text: 'Saved content' } },
  ];
}

test('request selects only actual tools and never invents recipient or campaign values', () => {
  const request = campaignDraftRequest({ ...fields, send: true });
  assert.deepEqual(request.tools, ['Mailchimp']);
  const body = JSON.parse(request.prompt.slice(CAMPAIGN_DRAFT_PREFIX.length));
  assert.equal(body.send, undefined);
  assert.equal(body.audience_id, fields.audience_id);
  assert.equal(body.body, fields.body);
  assert.equal(body.create_graphic, false);
  assert.deepEqual(request.resources.documents, []);
  assert.deepEqual(campaignDraftRequest({ ...fields, create_graphic: true, graphic_line: 'Approved line' }).tools, ['Mailchimp', 'Canva']);
  for (const change of [{ client: '' }, { body: '{{steps.secret}}' }, { cta_url: 'javascript:alert(1)' },
    { cta_url: 'https://user:secret@example.test/' }, { reply_to: 'not-an-email' }, { create_graphic: true },
    { subject: 'x'.repeat(151) }]) assert.throws(() => campaignDraftRequest({ ...fields, ...change }));
});

test('result requires a verified creation and content save for the same audience and campaign', () => {
  const rows = outputs();
  const result = savedCampaignDraft(rows, 'content');
  assert.equal(result.kind, 'campaign_draft');
  assert.equal(result.campaignId, 'campaign-42');
  assert.equal(result.body, 'Saved content');
  assert.equal(result.link, null); // No guessed admin or draft URL.
  assert.equal(primaryResultFromOutputs(rows, {}, { primary_step_key: 'content' }).kind, 'campaign_draft');
  assert.equal(savedCampaignDraft(rows.slice(0, 1)), null);
  assert.equal(savedCampaignDraft(rows, 'some_other_result'), null);
  for (const mutate of [
    (r) => { r[1].outcome_check = { status: 'unverified' }; },
    (r) => { r[0].provider_result.status = 'sent'; },
    (r) => { r[1].resolved_arguments.campaign_id = 'other'; },
    (r) => { r[1].resolved_arguments.expected_list_id = 'other'; },
    (r) => { r[0].critic = { action: 'reject' }; },
    (r) => { r.push({ operation: 'mailchimp.campaign.send', resolved_arguments: { campaign_id: 'campaign-42' } }); },
  ]) {
    const changed = structuredClone(rows); mutate(changed);
    assert.equal(savedCampaignDraft(changed), null);
  }
});
