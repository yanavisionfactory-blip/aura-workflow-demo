# Reddit Ads sign-in

Customers select **Reddit Ads → Connect**, sign in with Reddit, approve read
access, and choose their business and advertising account by name. AURA owns
the developer registration. Customers never create an app or enter a client ID,
client secret, access token, or refresh token.

This connection is separate from Reddit posts/comments. It requests only
`adsread`, with `duration=permanent`. Its operations read the authenticated
advertiser, businesses, owned advertising accounts, campaigns and performance reports. It does not
create or change ads, budgets, conversions or audiences.

## One-time operator setup

1. A verified Reddit business admin creates an **AURA** developer application in
   [Reddit Ads](https://ads.reddit.com) under **Business > Developer Portal**.
2. Register the exact backend callback: `<PUBLIC_URL>/v1/oauth/reddit-ads/callback`.
   Use the API origin, not the GitHub Pages frontend. If the deployment uses
   `OAUTH_CALLBACK_OVERRIDES`, register the exact override instead.
3. Configure `REDDIT_ADS_CLIENT_ID`, `REDDIT_ADS_CLIENT_SECRET` and
   `REDDIT_ADS_USER_AGENT` on both the API and worker. Use a descriptive user agent,
   for example `web:aura-workflow:v1.0 (by /u/<operator username>)`. Keep these
   values out of frontend/VITE settings and source control.
4. Deploy the reviewed backend and frontend changes. Until AURA's app credentials
   are present, the card stays unavailable; it never falls back to a developer-key
   form from the generic connector directory.
5. Test with a real advertiser: consent, authenticated `/me`, business and account
   lookup, account selection, campaign read, token refresh and disconnect/reconnect.
   Automated tests mock Reddit and do not establish production access.

## Performance reporting

`reddit-ads.report.get` reads account metadata, campaign metadata and every page of
the v3 reporting endpoint. Supply a selected `ad_account_id`; optional `since` and
`until` are inclusive UTC dates. Omit them for the available 24-month delivery
window through the latest completed hour. Older requested dates are clipped with
an explicit retention disclosure, never described as full lifetime history.

The response retains raw provider metrics and returns normalized spend, impressions,
clicks, CTR, CPC and purchase conversions/value/CPA/ROAS. Purchase click and view
counts remain separately available; other conversion events are not included.
Account attribution settings, currency and account timezone accompany the UTC
reporting window. Spend uses microcurrency / 1,000,000 and purchase value uses cents
/ 100. Missing metrics remain null. Campaigns without delivery rows are listed
separately and must not be reported as zero. Incomplete pagination fails the read.
Existing native `adsread` grants use the deployed read contract without another login.

Reporting contract: [Get a Report](https://ads-api.reddit.com/docs/v3/api/get-a-report).

Use Reddit's [application setup guide](https://ads-api.reddit.com/docs/v3/guides/quick-start/create-dev-app)
and [authentication guide](https://ads-api.reddit.com/docs/v3/authenticate-your-developer-application).
The [v3 API specification](https://ads-api.reddit.com/api/v3/openapi.json) is the
source for identity, business, account and campaign reads. The Ads API currently
does not require general allowlisting, but the developer application is required.

## Connection behavior

The backend exchanges the code using HTTP Basic app authentication, verifies the
Ads API identity and encrypts the grant in the existing workspace credential
vault. Refresh preserves the original refresh token if Reddit does not rotate it.
The browser receives only the authorization URL and sanitized account data.
Existing broker-backed Reddit Ads accounts retain their recorded reconnect route.

The account picker retrieves `/me/businesses`, then
`/businesses/{business_id}/ad_accounts`, following validated same-resource
pagination. It rechecks membership in that returned list when saving a selection.
Accounts shared into a business are not returned by this Reddit endpoint; this
limitation is shown in the picker. No arbitrary account ID text input is offered.
Account choices fill missing targets on new plans; explicit targets and reviewed
plans are preserved. Signing in as a different advertiser clears the old choice.

Google Ads already uses the existing production Pipedream sign-in and named
account picker. That flow is retained. Regular Reddit community access is a
separate integration and does not acquire Ads permissions through this change.
