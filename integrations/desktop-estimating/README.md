# AURA PlanSwift + Excel Windows connector

This connector makes installed PlanSwift and Microsoft Excel available as two connected tools in AURA. It reads existing takeoff directly using PlanSwift COM, reads an approved local rate book, generates a new formula-driven workbook, recalculates it in a separate Excel instance, and verifies the saved result. AURA can download that workbook through the authenticated connection.

**It does not install PlanSwift/Office, measure drawings, research or approve prices, change PlanSwift data, or certify measurement completeness.** Drawing calibration, scope and measurement review remain the estimator's responsibility. This first version generates the supplied standard workbook layout; arbitrary customer templates and macros are not supported.

## Standard connection (no API key or tunnel)

Use the normal **Connect** action for the app you want in AURA. The dialog is named
**Connect PlanSwift** or **Connect Microsoft Excel (Desktop)** and lists only that
app’s permissions. Each app can be connected, reconnected and disconnected independently.

1. On the Windows computer with the selected licensed app, download and open
   **AURA Desktop** from the connection dialog. Select **Install helper** once.
   The executable includes Python and its dependencies. It registers a per-user
   `aura-estimator:` link handler; no administrator account, service, startup task,
   firewall opening or public workstation address is created. Windows controls
   installation and application-launch permission prompts; do not disable them.
2. Select **Open AURA Desktop** in AURA. The helper shows the workspace and the
   selected app’s permissions before its first authorization. It checks and connects
   only that app; the other app does not need to be installed. A temporary pairing code is available as
   a fallback when opening the helper by link is unavailable. No secret key or
   provider API key is requested from the user.
3. Keep the helper open while AURA works. Use the existing workflow interface.
   If an app is unavailable, the dialog names it. Each browser attempt ends after
   two minutes and offers retry; closing it invalidates an unclaimed pairing.
   Reopening the installed helper restores its existing authorized connections.
   To connect the other app later, use its own **Connect** button and approve its
   permissions. Reuse the helper; no second installation is needed.

Connections created by the earlier combined flow remain valid. New authorizations
require the updated helper and an explicit app selection; old unclaimed combined
requests expire. If asked to update, close the old helper before opening the latest
download and selecting **Install helper**.

Pairing requests expire after ten minutes and are scoped to one app, their workspace and
initiating administrator. Repeated acknowledgement of the same device claim is
idempotent; another device cannot reuse it. Device credentials are stored in the
protected local configuration and AURA's encrypted credential vault. Disconnecting
an app in AURA revokes its actions on the next request without disconnecting another
app. Replace an app’s connected workstation only after disconnecting that app.

The helper makes outbound HTTPS requests to AURA's configured production service.
AURA queues only the bounded estimating operations below, never shell commands,
arbitrary paths or scripts. Commands expire, are claimed at most once and are not
redelivered after a lost response. The helper retries a completed result without
repeating the application action. An uncertain write still requires saved-report
reconciliation. A stopped helper produces an offline error, not an endless wait.

The Windows CI build checks the packaged runtime, GUI and workbook dependencies.
It does not have licensed PlanSwift or Excel and does not certify the real COM
workflow. The generated executable is not Authenticode signed; signing requires
the publisher's signing identity. The source archive remains available for review.
Validate the installed apps using the acceptance checklist below before production
reliance. Approved rates still belong in `Data/Rates/Approved-Rates.xlsx` beneath
`%LOCALAPPDATA%/AURA/EstimatingConnector`.

## Advanced: existing HTTPS bridge installation

The original manual endpoint API remains supported for installations that already
use an organization-managed tunnel. It is not the standard Connect flow.

1. Use a supported Windows workstation with licensed PlanSwift and desktop Excel. Install Python 3.12 from https://www.python.org/downloads/windows/ if needed. PlanSwift 12 requires a 64-bit client and its own registered COM program. Do not install this as a Windows service or on a server/Remote Desktop host: it runs in the signed-in user's desktop session.
2. Extract the complete AURA connector ZIP into a local folder. Inspect the files and run `./install.ps1 -PlanSwiftVersion 11` in PowerShell (use `12` only for PlanSwift 12). Follow your organization's PowerShell execution policy; the installer does not weaken it. Dependencies are installed in a private virtual environment. No service, startup task, firewall rule or public endpoint is created.
3. The default installation is `%LOCALAPPDATA%\AURA\EstimatingConnector`. Its files are restricted to the current Windows user and SYSTEM. The generated `config.json` contains a random connection key and a stable workstation identifier. Keep this file private. Rerunning the installer preserves it and any existing rates. To rotate a key, stop the connector, generate a fresh cryptographically random key of at least 32 characters, update the protected config and reconnect both apps in AURA.
4. Populate `Data\Rates\Approved-Rates.xlsx`. It starts **empty**, with instructions and the exact required headers. Enter separate material, labor and equipment amounts per unit, explicit zeros for non-applicable components, currency, a quote/source reference, and validity dates. Cost codes must match PlanSwift `Item #`; units must match the `Qty` property units. Use literal approved prices, not Excel formulas. Supported currencies: USD, CAD, EUR, GBP, AUD, NZD; line amounts round to two decimals.
5. Open and sign in to PlanSwift, open the intended job, and assign missing item codes/units before estimating. Start `Start Connector.cmd`. The connector binds only to `127.0.0.1:8765` and requires the connection key for every endpoint.
6. Expose this **loopback address** through your organization's authenticated HTTPS reverse proxy or tunnel. The connector itself also requires its bearer key; retain that check. AURA accepts a public HTTPS hostname on port 443, with no path, query or credentials in its URL. A tunnel must forward the `Authorization` header unchanged and allow a response time of at least 110 seconds. Do not expose the port directly or turn off authentication. No inbound Windows firewall opening is needed for an outbound tunnel.

An operator can use Cloudflare Tunnel (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) or an equivalent approved service. A temporary developer tunnel is started with `cloudflared tunnel --url http://127.0.0.1:8765` after installing the official client. Its random HTTPS address changes on restart: reconnect both AURA tools when it changes. Use a stable named tunnel for a continuing pilot. AURA does not create or pay for a tunnel account.

## Legacy endpoint connection and workflow inputs

1. Existing legacy installations continue using their saved connection. An administrator integrating the legacy bridge programmatically can use the authenticated `/v1/desktop-estimating/connect` endpoint with its HTTPS address, connection key and selected provider. The normal **Connect** UI now uses computer authorization instead.
2. Legacy **PlanSwift** and **Microsoft Excel (Desktop)** connections are independent too. Keep the relevant legacy connector and tunnel running while workflows execute or download files. A workflow that combines local takeoff and rate snapshots into an estimate requires them on the same computer; connecting an app by itself does not require the other app.
3. Start a workflow with both tools selected. Supply the exact open job name, drawing revision, rate-book filename, rate date, currency, material waste, markup and tax rules. Explicitly confirm that measurements have been reviewed. Choose **measurements** or **parts**; never price both scopes together.

Example task (replace all placeholders with real job settings):

> Use connected PlanSwift and Microsoft Excel (Desktop). Read the open job “PROJECT NAME”, drawing revision “REVISION”, using measurements only. I have reviewed the measurements and scope. List the rate books and use “Approved-Rates.xlsx” effective YYYY-MM-DD. Create a draft estimate in USD with 5% material waste, 10% markup, and 0% tax on materials. Read back the saved workbook and show the downloadable Excel estimate. Do not send messages.

For the combined estimate, connect both apps on the same computer so their local
snapshots are available to report creation. Other workflows may use one app alone.
The combined plan should contain these connected operations:

1. `planswift.job.read` -> takeoff `snapshot_id`.
2. `excel.ratebooks.list`, then `excel.rates.read` -> rates `snapshot_id`.
3. `excel.estimate.create` using both returned snapshot IDs and reviewed parameters.
4. `excel.estimate.get` for read-back. AURA also performs a deterministic write read-back.

The generated workbook contains Summary, Takeoff, Rates and Estimate tabs. Waste applies only to materials; labor/equipment use the unadjusted quantity. Markup is applied to direct cost. Tax applies to either materials or the subtotal including markup, as explicitly selected. Composite rates must not duplicate separately entered labor/equipment. Repeating identical snapshot IDs and parameters reuses one report. Revised source content produces a new report. Reports remain drafts.

## OpenAI agent handoff

The direct OpenAI runtime and the optional managed-agent runtime use the same AURA
provider gateway. The agent proposes the workflow; AURA validates its dependencies,
executes connected operations, and returns provider evidence for subsequent steps.
The managed runtime currently supplies reasoning only, with no direct desktop or
provider tools. Enabling it does not pair a workstation or grant app access.

Before plan review, AURA fills omitted estimate snapshot references when the plan
declares exactly one required prior PlanSwift read and one required prior rate-book
read as dependencies. It similarly binds a report read-back to one declared estimate
creation. These are references to future provider receipts, never generated IDs.
Explicit references are preserved. Multiple candidates, optional/conditional reads,
and missing dependencies are not guessed; normal validation blocks incomplete plans.
Missing measurement review, prices, project selection and tax rules are never filled
by this handoff. The combined estimate still requires snapshots on the same workstation.

An external OpenAI agent can use this execution route through AURA's orchestration;
the current ChatGPT MCP pilot only inspects connections and saves disabled drafts.
It cannot execute workflows. Computer use for measuring drawings is a separate,
unimplemented capability, not a consequence of selecting a different model.

## Failure behavior and boundaries

- Missing/ambiguous/expired rates, unmatched units, missing item IDs/codes, negative/nonfinite quantities, more than 5000 rows, modified snapshots and changed jobs fail before reporting success. No unit conversion or zero-price substitution is guessed.
- PlanSwift is scanned twice, including stable item identifiers, to reject a job changed during capture. Drawing revision is user supplied and labelled as such; the connector does not infer it from drawings.
- Only `.xlsx` files inside the configured Rates directory may be read. The remote API accepts snapshot/report IDs, never arbitrary file paths, formulas, shell commands or scripts. Its report downloads require the same key.
- Excel runs separately from the user's open workbooks. Macros and link updates are disabled. Every generated calculation is compared with an independent Decimal calculation after Excel saves and closes the workbook. Downloads verify the saved SHA-256.
- A single process lock and operation lock serialize work. Application operations run in a child process with a 90-second deadline. If Excel itself stops responding, close only the connector's generated workbook after checking the local console, then retry. The bridge does not kill the user's Excel/PlanSwift processes. An interrupted save is reconciled by report identity before another result is accepted.
- An offline workstation, stopped tunnel or revoked key cannot be displayed as a successful operation. Read errors can be retried. Writes require receipt reconciliation.
- Connection verification proves application reachability, **not** end-to-end live certification. Automated tests use controlled application adapters; a real Windows/PlanSwift/Excel acceptance run is still required before production reliance. Unattended use remains subject to AURA's operation certification rules.
- No Discord operation is included. Messaging requires a separate connected Discord tool and explicit authorization.

## Validate on a real workstation

Compare one known completed job with the generated workbook, then test quantity edits, drawing revisions, missing and expired rates, duplicate attempts, wrong units, workbook locks, interruption, restart and offline reconnect. Confirm all row counts and totals. Record installed versions, actual COM ProgID, source inputs, results and timing. Do not mark untested paths as passed.

PlanSwift COM references: https://github.com/PlanSwift/sdk-examples-2010 and https://help.constructconnect.com/planswift-developer-documentation-234. The read path uses `GetItem`, `ChildCount`, `ChildItem`, `Qty`, `Item #`, `GUID`, `Name` and `FullPath`; it does not change under-the-hood settings. For PlanSwift 12, the vendor documents `PlanSwift.PlanSwift12`; PlanSwift 11 uses `PlanSwift9.PlanSwift`. Confirm compatibility on the installed version.

Excel references: https://learn.microsoft.com/en-us/office/vba/api/excel.application.calculatefullrebuild and https://learn.microsoft.com/en-us/office/vba/api/excel.application.automationsecurity.
