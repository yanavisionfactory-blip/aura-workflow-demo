# Weekly account review from approved client exports

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
7. Create the plan, inspect its source-processing steps, and run it. The only
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
labelled fictional sources. `AURA_WEEKLY_REVIEW_V2` accepts only approved scoped
client inputs. Neither route accepts external write steps.

Backend tests cover every named platform, single-platform plan compilation and
provider dispatch, model drafting with a test double, scope/approval gates,
reporting status, attachment fidelity, dates, unknown values and provenance. Frontend
tests cover transport, templates, the input form, all native report sections,
download completeness and saved-result routing. Test fixtures contain fabricated
unit-test values and must never be passed off as actual client performance.
