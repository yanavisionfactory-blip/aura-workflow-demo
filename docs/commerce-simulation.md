# Four-tool e-commerce marketing simulation

`npm run build:commerce` builds the isolated public AURA workflow into
`dist/showcase/commerce-workflow/`. Run `npx vite --config vite.commerce.config.js --host 0.0.0.0`
for local development. The normal authenticated application and existing demos
have separate build entries and remain separate deployments.

The user explicitly authorizes simulated data. Harbor & Field is a fictional
Unstoprev client scenario, not a verified engagement. The `.example` product URL,
fabricated ASIN, product facts, offers, targets, accounts, attribution definitions
and all metrics are authored assumptions. Nothing is uploaded into a vendor.

Selecting **Run simulated workflow** executes four independent processors in
the browser, checking Seller Central first, then Google Ads, Meta Ads Manager
and Amazon Ads. Each receives a separate labelled input object and returns
computed weekly totals, full rows, source definitions, a SHA-256 and an execution
receipt. A fifth validation stage checks arithmetic, evidence and authored
scenario proposals. This is executable simulation, not a provider reporting API,
backend workflow-history entry or runtime model call. Copy and proposals are
authored for the exact packaged scenario; changed saved results are rejected.

The weeks are October 12–18 versus October 5–11, 2026, America/Chicago, USD,
at an illustrative common cutoff of October 22, 06:00 UTC. Each source retains
its assumed date basis and attribution window. Ad windows are provisional.
Search terms reconcile to their campaigns and are excluded from primary totals.
Seller unit-session percentage is units/session, not a unique-buyer rate.
Website total purchases are unavailable. Platform purchase credits, platform
attributed sales, Amazon total sales and available inventory remain separate.

The low-stock scenario has 30 available units and an illustrative 0.7 days of
cover; the replenished scenario has 900 and 21 days. Reserved stock and inbound
not received are excluded. Available stock, listing status and suppression gate
Amazon promotion proposals. Listing changes remain separate from targeting
experiments. Both stock cases produce the review package; a promotion hold does
not prevent diagnosis or drafting.

Results include the requested summary, three advertising tests, two Google
headlines and one description, two Meta primary texts, one Meta headline and
creative brief, one Seller title and three bullets, and six prioritized actions
with tool, campaign/ASIN, source links, changes, learning and approvals. Draft
review and complete evidence JSON download locally. Validated results restore
from this browser's local storage; they are not shared between users/devices.
No campaigns, copy, budgets, inventory, tasks or messages are changed.

## Render deployment

Use a Render **Static Site** with this Git repository, branch `main`, build
command `npm ci && npm run build:commerce`, publish path `dist/showcase/commerce-workflow` and
`SKIP_INSTALL_DEPS=true`. No account credentials, database, API URL, Clerk key,
worker or paid compute is required for this isolated simulation. Follow Render's
workspace selection requirement before creating the site. This deploy does not
migrate the authenticated AURA control plane or its existing customer data.

The build rejects imports of live API clients, Clerk or Base44. The HTML CSP
sets `connect-src 'none'`. Tests exercise actual processors, source alignment,
denominators, breakdown reconciliation, stock/suppression gates, receipts,
saved-data integrity, evidence links, draft counts and required copy limits.
