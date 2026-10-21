# Weekly account review from approved client exports

## Seven-platform simulation

Open `?weekly=1` and choose **Create seven-platform simulation plan** to use all
seven named platforms with authored sample rows. Review the plan and start it
in AURA. Seven `weekly.source.analyze` operations and one `weekly.review.prepare`
operation produce independent hashes/receipts, separate attribution, three
proposed experiments, six draft variants and a prioritized backlog.

This mode sets `simulationOnly: true`, a fictional training account, unconfirmed
real engagement/scope/reporting, and authorization for every simulated source.
It rejects real exports and real approval claims. Source metadata must match
the simulation-only mode. The existing approved-export route still permits
simulations only for Meta and Amazon. Email demo inputs cover Klaviyo welcome,
Mailchimp newsletter and HubSpot nurture cohorts; SMS is outside this route.
The destination is the AURA result and local downloads. No vendor connection,
fabricated vendor upload, campaign, budget change, external task or message occurs.

The main AURA application offers **Prepare weekly account review** on the task
screen. `?weekly=1` opens the same setup. This is an authenticated backend workflow,
separate from the public fictional Northline showcase.

## Run a review

1. Select one actual SmartSites client and confirm the engagement and scope with
   an approval reference. Select only contracted platforms: Google Ads, Meta Ads,
   Microsoft Advertising, Amazon Ads, Klaviyo, Mailchimp or HubSpot.
2. Enter the last complete reporting day, client timezone, currency and **actual
   common extraction cutoff**. Use two consecutive seven-day periods. Re-extract
   inconsistent source snapshots; changing a label does not align the data.
3. For each selected platform, identify the exact client account, export approver
   and approval reference. Specify attribution model/window/filters, date basis,
   click definition/bot filters, conversion event and value definition. Scope/approval references are the
   submitting user's attestations, not independently verified by AURA.
4. Download each blank CSV template, normalize an approved export into it and
   select the completed file. Never fill gaps with demo metrics. Use stable,
   unique evidence IDs; set `period` to `previous` or `current`; use actual campaign
   or message labels. Keep a single non-overlapping aggregation grain. `conversions`
   means the exact outcome specified in the source definition, including fractional
   attribution credits when applicable. Blank `revenue` means unavailable, not zero.
5. Add approved client goals/targets, brand facts, tone, claim restrictions and the
   brief approval reference. No offers, current ad copy or audience definitions are
   inferred from public agency services.
6. Confirm the selected client's reporting setup, exact HTTPS destination and
   access reference, or explicitly leave it unconfirmed. An unconfirmed setup is
   a visible handoff blocker; an internal draft can still be prepared. Confirmed
   setup is user-attested. AURA does not probe access or write the report there.
7. For Meta Ads or Amazon Ads only, choose **SIMULATED scenario** instead of an export when authorized. Confirm the simulation checkbox. AURA authors sample rows aligned to the chosen periods/currency; attribution settings are labelled assumptions. No live connection is created. All other scoped platforms still require approved exports. Scenario-dependent findings, tests, copy and backlog items retain simulation labels in the result and downloads. Do not use them as client results; validate with actual evidence before implementation or handoff.
8. Create the plan, inspect its source-processing steps, and run it. The only
   operations are `weekly.source.analyze` for each selected source and
   `weekly.review.prepare`. Inspect the saved summary, three experiments, six
   draft variants, backlog, source definitions and execution receipts. Download
   the full review and evidence packet locally if needed.

A workspace connection is not proof of client scope, correct account mapping,
usable reporting permissions or a successful vendor data query. The setup shows
matching workspace connections separately. Existing **Connect** controls own any
provider consent/credential flow. This export route needs no vendor connection and
**does not call a vendor reporting API**. It cannot connect an account or consent
on a user's behalf. There are no campaign launches, budget changes, message sends,
external task assignments or reporting-destination writes in the review workflow.

## Export contract

Paid CSV headers:

```csv
id,period,campaign,impressions,clicks,spend,conversions,revenue
```

Email CSV headers (Klaviyo, Mailchimp and HubSpot marketing email/automation
message cohorts):

```csv
id,period,campaign,delivered,uniqueClicks,conversions,revenue,unsubscribes
```

Optional `channel`, `segment`, `reach` and `recordType` columns are retained when
applicable. Email clicks are unique **per message**, not unique people across
messages. Do not combine overlapping segment rows, totals and their breakdowns.
Reach is not summed. SMS and non-message HubSpot pipeline/automation event exports
need a different schema and are rejected/unsupported by this route.

The Google search-term breakdown type
`nonbrand_search_term_breakdown_do_not_add_to_campaigns` is kept separate from
primary campaign totals. If metadata columns (period dates, timezone, currency,
cutoff, attribution, date basis, source or provenance) are repeated in a CSV, they
must match the request. An explicit simulated provenance cannot be accepted as
approved evidence. AURA cannot establish whether an uploaded value was fabricated;
the approver remains responsible for its origin.

Limits are seven sources, 200 KB per normalized source and 1.6 MB for the complete
packet. Inputs are retained as one explicit JSON attachment in the authenticated
run rather than squeezed into the 20,000-character task field. Model generation
has its existing independent 96 KB evidence limit and fails explicitly if exceeded;
use approved weekly aggregates rather than transaction-level exports. No input is
silently truncated to fit. Original CSV bytes, SHA-256, row counts and processing
receipts stay in the source result.

The report calculates weighted rates, flags configurable descriptive materiality,
and preserves each platform's conversion/value definition and date basis. It does
not blend ROAS, deduplicate orders across platforms, establish causal drivers or
claim statistical significance. New/zero baselines and unavailable value remain
visible. Test proposals require power, audience, asset, tracking, attribution
maturity and client review before implementation. Source IDs, creative links,
character limits and backlog dependencies are checked before a result is accepted.

The fixed-date export review is not offered as an automatic recurring schedule.
Start **New review with fresh exports** for a subsequent week.

## Release and verification

Deploy both frontend and Python backend from the same reviewed `main` release.
The legacy `AURA_WEEKLY_REVIEW_V1` sample continues to accept exactly the three
labelled fictional sources. `AURA_WEEKLY_REVIEW_V2` accepts scoped approved client inputs plus explicitly
authorized Meta/Amazon scenarios. `scope.simulated` must list exactly the scenario
platforms, with `simulationConfirmed: true`. A scenario source uses
`input_kind: simulated_scenario`, metadata `provenance: simulated`,
`simulationAuthorized: true`, a `SIMULATED_` filename, a simulation notice and
explicit click/outcome/value definitions. Every scenario row requires
`provenance: SIMULATED` and its source name; it cannot pass as an approved export.
Mixed results use `provenance: mixed_evidence`; source receipts, findings and
proposal flags preserve individual origins. Real and simulated metrics are never
aggregated. Neither route accepts external write steps.

Backend tests cover every named platform, single-platform plan compilation and
provider dispatch, model drafting with a test double, scope/approval gates,
reporting status, attachment fidelity, dates, unknown values and provenance. Frontend
tests cover transport, templates, the input form, all native report sections,
download completeness and saved-result routing. Test fixtures contain fabricated
unit-test values and must never be passed off as actual client performance.
# Seven-platform browser simulation

The weekly setup offers **Open seven-platform browser simulation**. This explicit route processes the authored Google Ads, Meta Ads, Microsoft Advertising, Amazon Ads, Klaviyo, Mailchimp and HubSpot samples inside AURA's browser UI. It runs seven CSV processors and a final arithmetic/proposal validation step, with SHA-256 source receipts, 32 independent comparisons, three authored experiment proposals, six draft variants and nine proposed backlog items.

The result declares `browser_executed_simulation`, `model_call_executed: false`, `provider_api_called: false`, and `external_writes: false`. It does not create a backend workflow-history entry or claim vendor connections. The fixed sample corpus prevents authored drafts from being applied to unrelated input values. Other exports retain the backend input/approval route. Email scenarios exclude SMS.

The completed result can be restored from local browser storage after evidence-hash, metric and reference checks. Download the Markdown review and JSON evidence packet for portability; saved browser data is not shared across devices. The query `?weekly=1&simulation=browser` opens this route. No campaigns, budgets, external tasks, client destinations or messages are changed.

