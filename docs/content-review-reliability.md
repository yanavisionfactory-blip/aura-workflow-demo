# Supplied-email review: release checks and operating limits

This template delivers a complete revised email, comment decisions, source
references and a saved handoff inside AURA. It does not send, schedule, upload,
publish or edit video. It is opt-in; these content checks do not apply to every
free-form report or every kind of creative asset.

## Start a review

Paste `AURA_CONTENT_REVIEW_V1`, a newline, and a JSON object into the AURA task
box. Supply `title`, `asset_id`, `version_id`, `source_url`, the complete `draft`,
`brief`, exact `cta`, and `comments` containing `id`, `text`, and `version_id`.
Each comment must belong to the selected version. Optional `min_body_words`
and `max_body_words` default to 60 and 100; `forbidden_terms` defaults to empty.
Use `mode: "simulation"` for rehearsal. For a real local approval use
`mode: "live"` and `supervisor_subject`, the designated reviewer's authenticated
AURA subject, not their display name. The reviewer must already have access to
the same AURA workspace.

The planner builds four fixed stages without a planning-model call:

| Stage | Output | Required checkpoint |
| --- | --- | --- |
| Intake | Original draft, source/version binding, comments and revision brief | Operator reviews the brief |
| Revision | Complete email plus one decision per comment | Operator can edit the actual saved text |
| Checked draft | Corrected complete email and comment decisions | Operator reviews or edits the final copy |
| Handoff | Exact checked email, source and handoff notes | Operator review in simulation; designated authenticated supervisor in live mode |

All four checkpoints are mandatory, including when optional tool reviews are
disabled. An edit updates the text consumed by downstream steps and final
verification; the original model receipt remains saved. Final assembly copies
the saved handoff verbatim. It cannot silently rewrite the approved email.

The supervisor's live-mode decision records actor, timestamp and SHA-256 of
the exact handoff. A different identity, stale text, or missing approval blocks
completion. Plan execution approval and AI QA are separate from content
approval. A later revision needs a new review round; approval never carries
to a new run or version. To revise customer-facing copy, edit the checked-draft
checkpoint before proceeding to handoff. A handoff edit that changes that copy
is rejected; start another round if it needs to change after that checkpoint.

## What the checks prove

The application parses exactly one Subject, Preheader, Body and CTA. It counts
whitespace-separated body words only, checks the exact CTA, source links,
explicit coverage of every comment ID exactly once, unfinished placeholders,
unresolved decisions and configured prohibited terms. It rechecks saved edits
and the current final version. One model repair is allowed for a malformed
generated email; a second failure stops the stage.

The computed result is displayed with its word and comment counts. Unsaved
edits do not inherit a previous version's check or approval badge. These checks
do not prove factual accuracy, brand fit, persuasiveness or that a comment was
handled well. The reviewer must judge those. Rejected comment decisions need
a reason and deserve particular attention.

Original input texts are bound by digests in the approved plan. The bindings
prove consistency with the supplied packet, not that an external proof export
is current or that the provider authorized it. PageProof metadata alone cannot
provide the comment text; the matching comments export remains necessary.

## Recovery and release validation

The regression suite exercises a real durable four-stage run with model/provider
responses mocked at the boundary, both unchanged and with a saved revision. It
opens fresh database sessions and redelivers worker jobs at every checkpoint,
then repeats review clicks. Each stage executes once; final copy matches the
current reviewed version. Tests also reject missing/wrong-version inputs,
weakened gates, fabricated source handoffs, failed word counts, stale approvals,
wrong supervisors, and exhausted-credit retry loops.

The existing runtime suites cover tenant isolation, permission and approval
revocation, provider timeouts, retry budgets, durable outbox dispatch and
provider write reconciliation. Run the complete backend/frontend CI, including
PostgreSQL integration tests, before release. Deploy only the tested main
commit through `backend-release.yml`, which checks canary, worker and API
readiness for that exact release.

Before treating the workflow as ready for unattended production, complete an
authorized live pilot with the actual draft, matching provider/export comments
and the designated human supervisor. Exercise an ordinary round, a changes-
requested round, and a resume after interruption. Record run/result URLs,
source versions, approval identity/timestamp and any manual repairs. Passing
mocked tests or a simulation does not establish those live-provider facts.
Publishing remains manual in this template.
