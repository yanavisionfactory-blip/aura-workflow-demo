# Elias reporting walkthrough

Standalone page: `/showcase/elias-blake/`.

Reuses Mason Green’s buildless AURA showcase layout and stylesheet, with a saved Google Ads / Reddit Ads reporting example. It loads no AURA application modules, credentials, backend or ad-provider requests. `connect-src 'none'` enforces this boundary.

The page includes saved-report table views, the existing four-slide presentation export, a screenshot of the actual AURA result, a manually advanced workflow walkthrough, source notes, CSV export and an editable prompt link to AURA. The prompt link does not automatically run a workflow. Original Google Sheet permissions are unchanged.

## Provenance

The corrected Cross-Platform Campaign Report was saved on 8 November 2026. Google Ads uses the earlier full-history response saved at 08:41 UTC: 1 campaign, EUR 173.231853 spent, 8,101 impressions, 193 clicks. Reddit uses the corrected account response saved at 18:18 UTC for 1–31 October 2026: 2 campaigns, EUR 64.674748 spent, 18,490 impressions, 79 clicks. The AURA pilot row matches the user’s screenshot (rounded EUR 32.92, 16,054 impressions, 69 clicks).

The presentation export is the corrected four-slide report already saved in Canva. The result-screen capture records the Canva design reconciliation output in AURA. This was an assisted recovery, not a demonstration of a new unattended execution. The walkthrough steps describe the reporting process; they are not a fabricated event log or timing replay.

Google and Reddit periods and conversion definitions differ. Do not combine conversion totals or present a platform ranking. Lead count is unavailable; zero attributed purchases is not zero leads. Calculate totals before rounding. No Elias account data, email addresses or session credentials are included.

## Validation

Run `node --test tests/eliasDemo.test.mjs`. Also check table tabs and keyboard navigation, all four walkthrough stages, presentation navigation, image dialogs, prompt edit/restore and the published page in the browser.
