# Easy Communications two-week AURA pilot

Separate public route: `/showcase/easy-communications/`. The base route shows AURA’s native task screen with Diana’s complete prepared pilot prompt already filled and Create plan enabled. The guided walkthrough starts with the same prepared request; it does not show a blank or generic task screen. Returning through New workflow restores this request. The opening prompt’s Tools used row preselects the full prepared workflow: Medium, LinkedIn, Meta Business Suite, Quora, the selected HubSpot/AURA tracker, Gmail, Google Calendar, Docusign and the selected measurement options. GA4 appears only when enabled. Changing CRM or measurement preferences updates this list without clearing the prompt. `?screen=results` opens the primary client record first. `?tour=1` runs the captioned 16-scene walkthrough; `?screen=connections`, `?screen=measurement`, `?screen=readiness` and `?screen=tool&tool=linkedin` are direct entry points.

The results page follows AURA’s native completion layout: centered heading, six visible pilot metric cards, estimated time saved, selected measurement tools, the main client record, supporting output dropdowns, action receipts, tool links and next actions. The review and results pages share the same prepared tool previews, including AI/manual editors and specific View in tool destinations. Metric definitions and source links remain on the separate report page; removing that workspace from the preview does not remove metrics. AURA, existing tools and combined reporting remain selectable from results and Connections. All counts come from the historical simulated fixture and time savings from its baseline/active time log; local editing does not invent new conversions.

The app reuses AURA's WorkspaceShell, CommandInput, ConfirmView, PlanStep, ExecutionView, ResultsHeading and PrimaryResult. Its normal flow is task → confirmation → plan → action review → execution → results. The restored native plan layout is preserved. The review page explains how users can inspect AI-prepared work, request changes, edit manually and approve exact actions. It shows the client opportunity and source history first, with the other 13 previews in collapsed sections: six social/Quora drafts, two contextual replies, discovery reply, calendar invitation, proposal, follow-up and agreement. Measurement remains available on its separate page and through the results. Each preview opens both prompt-based and manual editing with a live tool-screen preview. Saved edits are shared with standalone tool views and the export. Field changes clear recipient/message/terms or invitation approvals. Editing the agreement produces an unsigned draft and does not borrow completion evidence from the historical example. The plan leads directly from the six steps to Ready to start, with no separate Tools for this plan, Tell AURA what to change or schedule blocks. Each step retains Change and drag-to-reorder controls. Connection and measurement preferences remain in the header Connections control rather than adding a separate first-run page. There is no secondary demo navigation bar or custom marketing hero. It does not alter the live application or other showcases. The Base44 reference URL supplied by the user returned a permission/loading error during visual inspection; its opening-screen screenshot was available through the Base44 connector and was visually inspected. The native application components in this repository supply the remaining workflow layouts; the inaccessible editor itself is not claimed as verified.

## Inputs and provenance

Diana Akchurina's two user-specified public Medium articles were read on 23 October 2026. Source links and short takeaways are in `data.mjs`; each of six new adaptations retains its source identifier. No private email, private export or account data is included. Adaptations are proposed copy, not Diana-approved statements. No numerical claims from the articles are repeated. Quora question wording is illustrative; selecting a live relevant question remains a manual handoff.

All eight contacts, conversations, company names, stage events, agreement records, commercial terms and metrics are fictional. Reserved `.example` addresses prevent mistaking sample recipients for verified identities. The two-week dates are illustrative. A completed agreement example is a walkthrough of evidence verification, not a prediction or a real signature. Neither the document screen nor certificate screen is a legally operative artifact.

## Behavior

- HubSpot or AURA is the selected primary lead record. The same sample record preserves observed touchpoint and buyer-reported influence separately. Media, influencer and partnership inquiries have separate categories and are excluded from client conversion counts.
- AURA, existing-tool reports, or both can be chosen for measurement. Native tools retain their own roles: social activity, the selected primary lead record, meetings and signature completion. Time reporting remains visible with either AURA logs or a manual handoff from an existing time tracker. GA4 is optional and unavailable without a connected property/export. There is no inferred website data or causal sale attribution.
- Manual and AI-style editing work locally. AI-style editing uses deterministic prepared rules, no model call. Edits clear exact-copy approval. Publication requires approval of that revision. Quora cannot be published automatically in the model.
- Reply sending requires approval of both the current recipient and exact current text. Proposal sending also requires sample commercial-term approval. Calendar changes clear invitation approval. Sending and booking are local simulations only.
- Signed-agreement counts require a completed envelope, all required signers, a matching final-document record, a certificate record and verification. The Docusign screen includes an incomplete-evidence exercise that does not rewrite baseline historical metrics.
- Reports describe a prepared baseline. Browser edits, message exercises and sample invitations do not fabricate additional historical conversions.
- Local state is namespaced and can be reset or downloaded as JSON. The new editing format uses its own v2 key and imports v1 choices only on first open, so an older open walkthrough cannot strip new draft fields. Source cards, connection requirements, manual handoffs and the live-pilot inputs are visible.

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
