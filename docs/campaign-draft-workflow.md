# Campaign production in connected tools

Choose **Prepare a campaign in your tools** on the task screen, or open
`?campaignDraft=1`. This workflow saves an actual unsent Mailchimp email campaign
and optionally creates an editable Canva graphic. It does not require reporting
exports or fabricate account performance. The weekly export review remains a
separate workflow.

Use this route only when the selected client already uses Mailchimp. Google Ads,
Meta Ads, Klaviyo and other platforms are not represented as connected or writable
by this workflow. Adding them requires their own released operations and verified
draft-state semantics; no generic publish action or simulation is substituted.

## Inputs and execution

Supply the client name, approved-copy reference, exact audience ID **and name**,
campaign title, subject, preview text, sender, reply address, headline, complete
body, CTA text and HTTPS destination. These are user-supplied facts, not
independently verified client approvals. Optional Canva work also needs one short
approved line. No account, audience, product fact, offer or recipient is inferred.

The exact-field request `AURA_CAMPAIGN_DRAFT_V1` compiles into:

1. `mailchimp.audience.get`: read the selected audience and verify both ID and
   name. A mismatch stops the workflow before creating anything.
2. Optional `canva.presentation.create`: import a populated square creative
   using the supplied client name, headline, short line and CTA. The standard
   import readback must verify a completed design. This is a separate editable
   asset, not a published post or an email image upload.
3. `mailchimp.campaign.draft.create`: recheck the selected audience, then create
   a **regular** campaign with the exact reviewed settings. Automatic readback
   verifies the ID, audience, settings and Mailchimp's unsent `save` status.
4. `mailchimp.campaign.content.set`: check that the returned campaign ID still
   belongs to the expected audience and has `save` status, then PUT the reviewed
   full HTML and plain text. Read back both `/campaigns/{id}` and
   `/campaigns/{id}/content`; require matching content, audience and unsent state.

Each write uses AURA's normal concrete-content approval and execution pipeline.
Plan approval does not approve unresolved future writes. There are no send,
schedule, live-ad, audience-contact update, budget or task-assignment steps.
Missing native capabilities or readback grants stop planning rather than silently
choosing a different connector or client account. Existing connections may need
their capabilities refreshed or reconnected after this release.

The email renderer escapes supplied text, creates accessible English HTML and
a plain-text alternative, and includes Mailchimp address/unsubscribe merge tags.
Its language is English; other locales require a separate template. Review the
rendered email, merge fields, sender, consent, segmentation and eligibility before
any separately authorized future send. The draft targets the selected audience;
it does not infer a repeat-purchaser segment.

## Completion and recovery

The result shows the saved campaign ID, audience, sender settings and complete
plain text only after both creation and content-save receipts are accepted and
verified. A create-only receipt, mismatched campaign/audience, incomplete content,
unverified write or a send operation cannot produce the unsent-campaign success
view. No admin/editor URL is guessed. Optional Canva results use returned design
identities and links. Tool activity retains the real provider receipts.

If a write response is lost, use normal recorded-receipt reconciliation. Do not
recreate a campaign blindly. If the content step fails after creation, an empty
unsent campaign may remain; the workflow stays incomplete and the saved ID is
available in activity. Concurrent edits or provider content rewrites can cause
readback failure; inspect the actual resource before retrying. This does not
claim that matching a stored draft establishes deliverability or live test results.

## Validation

Tests exercise the audited compiler and normal preflight, real provider method
dispatch against mocked HTTP, wrong-audience and non-draft guards, exact content
readback, review requirements, optional Canva scope, result identity and safe UI
rendering. These are not live Mailchimp/Canva conformance tests. Deploy frontend
and backend from the same reviewed release, then validate with a dedicated account
and a separately approved draft-only run before client use.

Provider contracts: [create campaign](https://mailchimp.com/developer/marketing/api/campaigns/create),
[set content](https://mailchimp.com/developer/marketing/api/campaigns/upsert-content),
and [get content](https://mailchimp.com/developer/marketing/api/campaigns/get-content).
