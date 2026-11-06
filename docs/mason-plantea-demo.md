# Mason’s Plantéa saved-output demo

Public entry: `/showcase/mason-green/`. This independent, buildless page is copied by the normal Vite build. It does not load AURA account clients or call providers. It opens without sign-in.

The snapshot contains 37 rows and six columns captured from the rendered **Saved Google Sheets cells** in the existing Plantéa September 2026 result. The Google Sheets write receipt covered A1:G37, but the saved read-back covered A1:F200. Do not label this a fully verified workbook. `saved-cells.csv` preserves the same cell text; the KPI view formats the 0.026 target as 2.6%. Other views select existing rows rather than introducing new metrics.

The page records four page-read attempts, including one denied Dermalogica/Unilever source, one prepared report and 37 written rows. The original brief requested Claude; the saved report used ChatGPT. The run required fixes and correction prompts and retained a pending final review. No independent autonomous repeat, business performance, revenue uplift or time savings is claimed. The historical illustrative KPI-pilot figures are not included.

The included screenshot is the captured AURA page, not a fabricated provider result. Current product prices, industry benchmarks and calculated scenarios remain distinct from September company actuals. Raw third-party page text and private pilot correspondence are not published.

“Try this workflow in AURA” uses the existing `?prompt=` input route. It carries only the editable prompt, never saved-run, account, connection or approval state. Copying feedback is local and does not send a message. The original Google Sheets link preserves its existing permissions; the public snapshot and CSV do not depend on access to that workbook.

Validation: `node --test tests/masonDemo.test.mjs`, normal frontend CI, and live browser review. Responsive styles cover narrow screens; do not claim mobile-device testing unless it has been performed. The demo is shipped as part of the existing AURA GitHub Pages site; no separate account or external integration is provisioned.
