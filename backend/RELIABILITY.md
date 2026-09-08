# Workflow reliability release gate

Every release runs the same contract, planning, execution, approval, provider outcome,
tenant isolation and subprocess crash tests. PostgreSQL gates cover advisory ownership,
concurrent outbox publication, RLS, stale recovery and its durable budget. CI preserves
JUnit results as `workflow-release-evaluation`.

## Operational controls

- API: `RECOVERY_SCHEDULER_ENABLED=true` starts a 15-second recovery/outbox loop.
  PostgreSQL elects one tick owner across API replicas. Celery Beat is not required
  for recovery. Scheduled business workflows still use the existing schedule dispatcher.
- `STALE_RUN_SECONDS=600`: inspect queued, planning, running and recovering runs.
  A live execution lock prevents recovery. Approval-paused and terminal runs are excluded.
- `MAX_RESTART_RECOVERIES=3`: persist recovery count, then pause with saved evidence.
- Database transitions atomically create tenant-scoped dispatch intents. Publish failures
  remain pending with capped backoff. Delivery is at least once; per-run ownership and
  provider receipts prevent replay of known or uncertain writes.
- `MAX_PROVIDER_ATTEMPTS=3`: shared across a step's deliveries and alternative reads.
  Writes have one attempt. Authorization and invalid requests do not auto-retry.
- `DELIVERY_BUDGET_SECONDS=180`, `MAX_MODEL_CALLS_PER_DELIVERY=16`,
  `MODEL_CALL_TIMEOUT_SECONDS=30`: model and provider work have bounded budgets.
- `PARALLEL_READS_ENABLED=true`: up to three independent typed native reads, at most
  two per connector. No write/approval barrier crossing; attempts commit before IO.
  Schema, trust and permission checks remain required. Database operations are serial.
- Completion enqueues owner-scoped memory indexing separately. Explicit saved workflows
  can reuse a verified plan only for the same owner, prompt, inputs and contract hashes;
  current capability validation and a fresh approval still apply.

`GET /v1/runs/{id}/evaluation` reports planning duration, first useful result, completion
wall time (including approval waits), active execution time, calls, provider attempts,
recoveries, replans, tokens and configured cost estimates. Unknown costs remain null.
Latency targets should be set from observed distributions, not mocked test timings.

## Connector certification

A verified OAuth connection does not certify its operations. Native contracts expose
input/output schemas, permission scope, evidence tags, retry semantics and a contract
hash. Typed output schemas cover supported Notion, Gmail, Calendar and Jira reads and
receipts. Other output shapes remain explicitly provisional. No operation is advertised
as execution-ready merely because it authenticates or passes fixture-only tests.

Notion page metadata cannot supply `page_body`; compilation rejects that declaration
and unsupported typed output references. Plans receive the same operation guarantees
used by runtime validation and generated conformance tests. Nested/paginated body content
still requires explicit reads; a first page is not a guarantee of complete content.

Live certification requires dedicated accounts and fixtures. Put credentials in an
environment variable containing JSON. Never commit credentials, receipt ledgers or
private fixture contents. Example fixture structure:

```json
[{
  "id": "notion-create-fixture-v1",
  "connector": "notion",
  "operation": "notion.page.create",
  "dedicated_test_account": true,
  "expected_account_id": "EXACT_TEST_ACCOUNT_ID",
  "credentials_env": "AURA_NOTION_TEST_CREDENTIALS",
  "arguments": {
    "parent": {"page_id": "DEDICATED_TEST_PARENT_ID"},
    "properties": {"title": {"title": [{"text": {"content": "AURA release fixture"}}]}}
  }
}]
```

Run `python -m app.release_evaluation --fixtures fixtures.json --ledger ledger.json
--report report.json --allow-writes`. Run it again with the same ledger to prove receipt
reuse and read-back without another write. Account identity must match before any action.
The ledger records dispatch before IO and receipts before validation; an uncertain write
stops for reconciliation. Keep the ledger durable and run one process per ledger.
Use fixture create and update cases for each supported write, preserving their resource IDs.
Clean up fixture resources in the dedicated account after retaining validation evidence.

A connector is ready only when every advertised supported action has passing contract,
workflow and failure gates plus current live create/update/read-back/restart evidence for
its exact contract hash. Unsupported writes, missing account fixtures, failed checks and
unverified semantics must remain visible gaps. The runtime currently exposes conservative
`execution_ready=false` until that certification process is completed.

## Assurance controls and operator workflow

The Workflow health panel provides the current operation matrix, blocked-run diagnostics,
observed performance and a read-only recovery canary. All data is tenant-scoped. Creating
canaries, importing/revoking certification and viewing workspace operational aggregates
require administrator access. Regular workspace users can inspect operation readiness
and individual run diagnostics.

`GET /v1/assurance/operations` derives coverage from deployed contracts and reports
provisional/unverified/certified status for each installed operation. Provisional output
shapes and missing write read-back checks are explicit blockers, not execution guarantees.
Scheduled, polling and webhook runs are marked unattended. Existing automated runs are
recognized by their origin audit events. The executor requires current certification for
each unattended operation before provider IO, including after approval/resume. Supervised
runs continue through their explicit approval and verification path. Certification is
connection- and contract-specific and automatically expires. Revocation invalidates the
operation's existing certificates; revoked reports cannot be imported again.

`POST /v1/assurance/certifications` accepts a signed report from the trusted certification
environment. Configure `CERTIFICATION_SIGNING_KEY` there and on the API; never in the
frontend, fixture files or repository. `python -m app.certify_report --reports ...
--scope scope.json --output signed.json` signs evidence only after required live scenarios
pass for the same provider account, release and contract. The scope file supplies the
workspace ID, tool ID, connector, operation and connection fingerprint shown by the matrix.
The signing authority must verify this deployment scope; do not accept untrusted reports
into that environment. Certificates expire after seven days by default, at most thirty.

For each fixture operation, retain the first successful execution report, rerun its ledger
for receipt-resume evidence, and run a separate fixture ID with `simulate_lost_response:true`.
The first lost-response invocation intentionally exits unsuccessfully after the dedicated
write. The test observer retains a witness separately from the execution receipt. A second
invocation must use read-back, without another write, before reporting the lost-response
scenario as passed. Never use customer accounts or recipients for these tests. Missing
fixtures, unsupported checks or unknown outcomes do not produce a passing attestation.

Notion block reads now traverse pagination and nested children, bounded to twenty provider
requests and one thousand blocks. The result retains raw blocks plus a nested-child map
and explicit coverage metadata. Exhaustion or non-advancing cursors prevent complete-body
verification. Collection completeness requirements also inspect provider continuation
markers. Unknown Notion and Jira update outcomes can reconcile using the approved resource
ID and exact requested fields. Success means the requested state is observed, not proof
that this particular request created that state. Other unknown writes continue to pause.

### Controlled production abandonment

Enable `RECOVERY_PROBE_ENABLED=true` on the API to allow administrators to create a canary.
The fixed workflow reads public Berlin weather twice. After the first accepted checkpoint,
its task yields normally, preserving a running workflow without holding worker ownership.
Only a server-created `recovery_probes` row can trigger this behavior; prompts and connector
outputs cannot. No worker or production service is stopped. The elected production scheduler
recognizes this fixture after thirty seconds, reacquires it through the normal outbox and
worker path, and resumes the second read. Approval-paused and completed guard runs are
created alongside it. Passing evidence requires both reads to have exactly one attempt,
a recovery audit event, a completed run, and unchanged guards. This proves abandoned-run
recovery in production; it does not simulate a machine or database crash.

`POST /v1/assurance/recovery-probes` starts the check. GET the same collection or
`/v1/assurance/recovery-probes/{id}` to inspect evidence. Canaries are administrator-only,
read-only, and contain no customer resource IDs. Model/provider failures remain visible
and cannot be marked passed. PostgreSQL and isolated process crash gates remain separate.

### Performance and support gates

`GET /v1/assurance/performance` returns p50/p95 distributions from the latest two hundred
workspace runs, with sample counts and explicit missing measurements. Configure
`PERFORMANCE_TARGETS_JSON` with metric-name-to-p95-ceiling mappings once representative
measurements exist. At least `PERFORMANCE_MINIMUM_SAMPLES` (default thirty) are required
per target. With no targets the status is baseline_only; insufficient data cannot pass a
performance gate. Production load certification remains separate from these observations.

`GET /v1/runs/{id}/diagnostics` identifies the next action, responsible party, attempt
status and pending dispatch count. `/v1/assurance/operations-health` exposes up to one
hundred active or blocked runs for administrator triage. Uncertain writes recommend
reconciliation and explicitly prohibit repeating the write. These endpoints expose no
credentials or raw provider error payloads. Existing provider/model duration, token and
cost metrics remain available in the run evaluation endpoint.
