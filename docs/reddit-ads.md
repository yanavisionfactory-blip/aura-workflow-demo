# Reddit Ads reporting

AURA has a separate **Reddit Ads** connector for live, read-only advertising
workflows. A Reddit social connection does not authorize this connector. It
supports identity checks, businesses, ad accounts, campaigns, ad groups, ads and
performance reports. Campaign creation, budget changes, launches, conversion
uploads and audience writes are not exposed.

## Operator setup

1. Register an AURA-owned Reddit Ads developer web application using Reddit's
   [developer app setup](https://ads-api.reddit.com/docs/v3/guides/quick-start/create-dev-app).
2. Register the exact backend callback:
   `${PUBLIC_URL}/v1/oauth/reddit-ads/callback`. If using
   `OAUTH_CALLBACK_OVERRIDES`, register that exact override instead.
3. Set `REDDIT_ADS_CLIENT_ID` and `REDDIT_ADS_CLIENT_SECRET` in the backend's
   secret settings. These are application credentials, never browser variables
   or customer-pasted access tokens.
4. Deploy the reviewed release, open **Connect → Reddit Ads**, and authorize the
   intended Reddit identity. AURA requests only `adsread`, with permanent access
   for token renewal, and verifies `/api/v3/me` before saving the connection.
5. List businesses and accounts, then supply the intended client's exact ad
   account ID for reports. Account lists exclude accounts shared with a business;
   `reddit-ads.account.get` can verify an explicit shared-account ID. Never infer
   client identity from the first account in a list.

Without both app settings, Reddit Ads remains visible but unavailable. A configured
app is not a connected user account. Connection and workflow execution still use
AURA's workspace authorization, encrypted credentials and exact operation grants.
Deployment alone does not verify real account access; complete a live read after
consent before treating the integration as production-certified.

## Report contract

`reddit-ads.report.get` requires `ad_account_id`, `starts_at`, and `ends_at`.
Both date boundaries use `YYYY-MM-DDTHH:00:00Z`. An optional `time_zone_id` selects
the reporting time zone; it defaults to UTC. Defaults request delivery and purchase
metrics by date and campaign. The manifest enumerates supported fields and
breakdowns. Reports verify the exact account first and return its metadata.

The adapter follows Reddit's pagination URLs only on the original API host and
resource, retaining the report body for every page. Malformed responses, repeated
pages, changed accounts, or the 20-page bound fail the operation rather than
present partial data as a complete report. Narrow the period if the bound is hit.
Provider permission, rate-limit and service errors propagate through AURA's
existing execution/recovery flow.

Results include raw rows, original pages, report inputs, account currency/settings,
source URL, retrieval time and a link to Reddit Ads Manager. Raw spend, CPC and
ECPM use microcurrency units (divide by 1,000,000); purchase total value uses minor
currency units (divide by 100). The adapter does not silently convert or aggregate
these values. Preserve attribution settings and metric freshness from the original
pages. Missing and null values stay missing or null; actual zero values remain zero.
Reddit-attributed purchases/value must stay separate from deduplicated sales orders
and company revenue when writing a KPI dashboard or Google Sheets workbook.

## API evidence and verification

Implementation checked against Reddit's official documentation on 2026-11-06:

- [OAuth consent, token exchange and renewal](https://ads-api.reddit.com/docs/v3/guides/quick-start/authenticate)
- [API version lifecycle](https://ads-api.reddit.com/docs/v3/guides/versioning):
  v3 is stable through Q3 2027; v4 is preview in Q4 2026.
- [Account discovery](https://ads-api.reddit.com/docs/v3/api/list-ad-accounts-by-business)
- [Performance reports and metric units](https://ads-api.reddit.com/docs/v3/api/get-a-report)
- [Reporting fields](https://ads-api.reddit.com/docs/v3/guides/programs/reporting/metric-reference)

Automated checks cover the OAuth wire contract, token renewal, permission denial,
catalog readiness, separation from ordinary Reddit, exact account dispatch,
report request/response handling, missing metrics, and pagination boundaries.
These are mocked contract tests; they do not prove a live Reddit Ads account works.
