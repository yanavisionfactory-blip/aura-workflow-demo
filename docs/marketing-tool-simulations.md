# Marketing tools workflow

Open `/marketing-tools` in the authenticated AURA application and choose **Run
workflow**. AURA coordinates native Google Ads and Mailchimp account discovery
with separate Meta Ads and Klaviyo browser simulation adapters. The results are
saved to the existing workspace-scoped Delivery API and opened at `/results/:id`.
No backend deployment or change to a live connection is needed.

| Tool | Operation | Execution |
| --- | --- | --- |
| Google Ads | `google-ads.list-account-id-options` | Native account metadata read |
| Mailchimp | `mailchimp.audiences.list` | Native audience metadata read |
| Meta Ads · Simulated | `meta-ads-simulated.review.get` | Separate browser simulation adapter |
| Klaviyo · Simulated | `klaviyo-simulated.lifecycle.get` | Separate browser simulation adapter |

The browser creates one native child workflow. Before approval it checks that
the compiled plan contains exactly the two named read operations, from their
native owners, with bounded arguments and no fallback actions or conditions.
Unexpected plans are never approved. Planning, authorization, execution and
missing-response failures stay visible; they do not become simulated native
successes. Saved results re-read native evidence from the actual child run.

The two simulation adapters execute independently of native connectivity. Each
returns computed weekly totals, its own authored demo assets and experiment,
source rows, operation, execution time, fixture SHA-256 and explicit
`provider_api_called=false`, `external_writes=false`, `native_drafts_saved=false`.
Their mode is `browser_simulated_tool_adapter`; they are not vendor calls or
backend RunStep records. The saved review retains their actual browser execution
ledger. No AURA Intelligence operation or report-composition step executes them.

The four tool views show real native discovery results or blockers alongside
clearly labeled simulations. Proposed Google Search copy and the Mailchimp
invitation come from the synthetic brief and are labeled unsaved proposals;
neither native platform is claimed to have created them. Native performance is
not fabricated. Maple & Ember Coffee is fictional: verified same-client account
selection is still required before native performance queries or implementation.

The fixture is `src/data/marketing_tools_maple_ember_v1.json`. Its scenario uses
October 12–18 versus October 5–11, 2026, America/New_York and USD. All approvals,
product facts and metrics in the fixture are demo assumptions. Reserved
`.example` destinations are placeholders. Attribution stays separate. Zero-send
replenishment has no conversion rate or demonstrated lift. No contacts are read,
campaigns or budgets changed, native drafts created, messages sent or flows
activated. Only the review record and read-only child workflow are saved.
