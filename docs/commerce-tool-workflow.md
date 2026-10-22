# Four-tool commerce workflow inside AURA

Open `/commerce-tools` in the signed-in AURA application and choose **Run
four-tool workflow**. This uses AURA's existing connection, planning, approval,
RunStep execution and workspace Delivery APIs. It is not the standalone public
browser simulation and does not execute an AURA Intelligence operation.

The workflow connects four separate, explicitly simulated MCP tools hosted by
`server/commerce-tools.mjs` on Render. All source data is the fictional Harbor &
Field travel-mug scenario. These services have no vendor credentials and expose
no campaign, budget, listing, inventory, publishing or messaging operation.

| Tool | Remote operation |
| --- | --- |
| Amazon Seller Central · Simulated | `seller_central_weekly_review` |
| Google Ads · Simulated | `google_ads_weekly_review` |
| Meta Ads Manager · Simulated | `meta_ads_weekly_review` |
| Amazon Ads · Simulated | `amazon_ads_weekly_review` |

Seller Central executes first. The three advertising reviews depend on its
completed native step. Each remote operation validates the exact authorized
scenario, processes its own source rows and returns independently calculated
weekly totals, attribution definitions, draft assets/test and a timestamped
receipt with input SHA-256. They are real HTTP/MCP calls to simulators, not calls
to Google, Meta or Amazon reporting APIs. Proposed copy and test specifications
are deterministic scenario drafts, not vendor drafts or generated model output.
AURA's normal coordinator can summarize the returned evidence, but no separate
report-composition tool substitutes for the four calls.

The browser rejects an unexpected plan, extra tool step, unapproved arguments,
missing/malformed remote receipts, unfinished run or advertising execution
before the Seller step finishes. Completed native evidence is saved with the
review package in the current workspace. Opening saved results reads persisted
evidence and does not execute the tools again. Failed native runs are linked
with their actual status; missing tool evidence is never synthesized locally.

The results page has an action package, four tool views, three proposed tests,
Google and Meta copy, Seller title/bullets, a stock/listing gate and prioritized
approval checklist. Website orders are unavailable, platform attributed outcomes
remain separate, and Amazon total ASIN sales are never added to ad-attributed
sales. All client facts, offers, targets, dates and metrics are marked simulated.

Deploy the data service with Node, build command
`node --check server/commerce-tools.mjs`, start command
`node server/commerce-tools.mjs`, and the free web-service plan. It binds the
Render `PORT` on `0.0.0.0`; `/health` is a side-effect-free readiness endpoint.
No additional dependency, database or secret is required. Keep
`COMMERCE_ENDPOINT` in `commerceToolWorkflow.mjs` aligned with the service URL.

Validation: `node --test tests/commerceToolWorkflow.test.mjs`, `npm test`,
`npx vite build`, and a completed signed-in native run with all four receipts.
