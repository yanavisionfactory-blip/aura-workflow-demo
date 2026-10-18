# AURA SEO Bridge

This first-party adapter lets AURA call the installed RankMath and Imagify
plugins on WordPress 6.3+ without requiring WordPress's newer MCP/Abilities
registration layer. It delegates to vendor execution classes and permission
checks; it does not implement a substitute scoring or image optimization engine.

Install `aura-seo-bridge/` as a normal WordPress plugin. Keep RankMath 1.0.280+
and Imagify 2.3.4+ active. Configure the Imagify API key in WordPress. In AURA,
connect RankMath and Imagify using the existing verified WordPress Org account.
No new account, key, core update or UI redesign is needed.

The status probe verifies which vendor operations exist. A missing bridge,
missing vendor class, denied plugin permission or invalid Imagify key prevents
activation. Plugin versions may change their internal execution classes; re-test
the connection after vendor updates.

## Operations

| Provider | Operations | Limits |
| --- | --- | --- |
| RankMath | Read SEO metadata, get content-analysis inputs/tests, save SEO metadata and read it back | Metadata writes only on draft, pending or private posts. No publish operation. The vendor scoring engine runs in the editor; analysis inputs are not a newly computed score. |
| Imagify | Read statistics, read media status, optimize one media attachment | Native API-key/quota/confirmation checks remain. Existing optimization is reused. Queued jobs are reported as queued; check status for completion. No purchases or billing changes. |

All bridge routes require an authenticated WordPress user with `manage_options`.
Each execution additionally checks the vendor ability's permission callback and
object access where relevant. RankMath writes use its registered `updateMeta`
REST route and verify all saved fields afterward.

AURA references the parent WordPress connection rather than storing another
password. The backend checks broker account ownership before retrieving the
specific WordPress grant for a server-side HTTPS request. Credentials never
enter planner context, API responses, logs or deliverables. The destination comes
from the existing broker account, never from workflow arguments. Redirects,
non-public destinations and non-HTTPS URLs are rejected. Disconnecting the
parent also disables its plugin connections; every execution rechecks the parent.

To remove the adapter, disconnect its two AURA entries and deactivate/delete
AURA SEO Bridge in WordPress. Existing post content and vendor plugins remain.

## Validation

`php -l aura-seo-bridge/aura-seo-bridge.php`

`php tests/bridge-test.php`

The PHP contract harness uses vendor boundary doubles to check access denial,
native delegation, draft-only writes, exact read-back, idempotent recovery and
Imagify confirmation/queue handling. Backend tests cover workspace binding,
parent revocation, credential ownership, URL restrictions and safe failures.
These tests do not establish a live provider connection; verify that separately
in AURA against the intended WordPress site.
