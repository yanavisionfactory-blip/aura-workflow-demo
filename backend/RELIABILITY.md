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
