# Easy Communications two-week AURA pilot

Separate public route: `/showcase/easy-communications/`. The base route shows the primary client record first. `?tour=1` runs the captioned 14-scene walkthrough; `?screen=connections`, `?screen=measurement`, `?screen=readiness` and `?screen=tool&tool=linkedin` are direct entry points.

The app reuses AURA's WorkspaceShell, CommandInput, PlanStep and ExecutionView. It does not alter the live application or other showcases. The Base44 reference URL supplied by the user returned a permission/loading error during visual inspection; no claim of verifying that preview is made.

## Inputs and provenance

Diana Akchurina's two user-specified public Medium articles were read on 23 October 2026. Source links and short takeaways are in `data.mjs`; each of six new adaptations retains its source identifier. No private email, private export or account data is included. Adaptations are proposed copy, not Diana-approved statements. No numerical claims from the articles are repeated. Quora question wording is illustrative; selecting a live relevant question remains a manual handoff.

All eight contacts, conversations, company names, stage events, agreement records, commercial terms and metrics are fictional. Reserved `.example` addresses prevent mistaking sample recipients for verified identities. The two-week dates are illustrative. A completed agreement example is a walkthrough of evidence verification, not a prediction or a real signature. Neither the document screen nor certificate screen is a legally operative artifact.

## Behavior

- HubSpot or AURA is the selected primary lead record. The same sample record preserves observed touchpoint and buyer-reported influence separately. Media, influencer and partnership inquiries have separate categories and are excluded from client conversion counts.
- AURA, existing-tool reports, or both can be chosen for measurement. Native tools retain their own roles: social activity, CRM stages, meetings and signature completion. GA4 is optional and unavailable without a connected property/export. There is no inferred website data or causal sale attribution.
- Manual and AI-style editing work locally. AI-style editing uses deterministic prepared rules, no model call. Edits clear exact-copy approval. Publication requires approval of that revision. Quora cannot be published automatically in the model.
- Reply sending requires approval of both the current recipient and exact current text. Proposal sending also requires sample commercial-term approval. Calendar changes clear invitation approval. Sending and booking are local simulations only.
- Signed-agreement counts require a completed envelope, all required signers, a matching final-document record, a certificate record and verification. The Docusign screen includes an incomplete-evidence exercise that does not rewrite baseline historical metrics.
- Reports describe a prepared baseline. Browser edits, message exercises and sample invitations do not fabricate additional historical conversions.
- Local state is namespaced and can be reset or downloaded as JSON. Source cards, connection requirements, manual handoffs and the live-pilot inputs are visible.

## Integration boundaries

No Diana account is connected by this demo. LinkedIn access must be verified for the chosen author and feature; personal messaging is not assumed. Facebook uses an approved Page, with relevant publishing, engagement and messaging access verified before a live run. Quora remains manual. HubSpot, email, calendar and signature provider availability are checked before live writes; manual handoffs are provided. AURA never signs an agreement for Diana.

Reference documentation used to constrain the concept:

- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- https://knowledge.hubspot.com/records/associate-records
- https://developers.docusign.com/platform/webhooks/connect/
- https://support.docusign.com/s/document-item?bundleId=oeq1643226594604&language=en_US&topicId=gpa1578456339545.html

The independent Vite build rejects live account modules and ships a `connect-src 'none'` policy. It is not wired to production account clients, OAuth, external forms or live data calls.

## Validation

`node --test tests/easy-communications.test.mjs` checks revision-bound approval, manual Quora handoff, exact-recipient/message gating, signature evidence, inquiry separation, time calculations, state recovery and export provenance. Run the repository tests and complete build before publishing. Review the deployed guided flow, provider screens, measurement choices and mobile layouts through the supported browser tools.
