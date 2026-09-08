# Backend agent development: first implementation

This change extends the existing runtime on `python-control-plane`. It adds no
schema migrations and does not change the deployed Railway branch.

## Implemented

- **Planner / executor:** normalize bracket references before dependency analysis;
  infer dependencies through named output variables; reject missing variables and
  pre-execution self-references; validate reduced-scope references; carry input
  names and repair requirements through the staged planner fallback.
- **Durable execution:** PostgreSQL session advisory locks serialize planning and
  execution deliveries for each workspace/run. A dedicated connection holds the
  lock across checkpoint commits. Provider receipts and resolved arguments are
  committed with successful attempts before semantic review. Review can resume
  without another provider call. A previously attempted write without a receipt
  has an unknown outcome and requires reconciliation, not automatic replay.
- **Verification:** output-review outages and contract/policy failures pause the
  run. A final outcome-verifier agent compares accepted connector evidence with
  the original objective and approved plan. Missing/invalid evidence cannot mark
  a run complete. `result.verification` records status, cited step IDs and fixes.
- **Recovery:** existing bounded read repairs and approved fallbacks remain.
  Rejected results can be reviewed again. Changed write fallbacks after an
  attempt are blocked; recovery no longer raises write trust scores to the
  execution threshold. Final verification can be retried through the existing
  resume endpoint, without replaying completed steps.
- **Memory:** saved workflow variables remain explicit reusable defaults.
  `POST /v1/runs` additionally accepts `memory_run_id` and `memory_bindings`,
  mapping new input names to selected prior `steps.<key>.<field>` paths. Only
  verified completed runs created by the same authenticated subject in the same
  workspace can supply memory. A `run.created` audit event stores provenance.
  Older runs without recorded ownership cannot supply this new memory feature.
  Input precedence is saved defaults, selected memory, then explicit inputs.
- **Evaluation / tracing:** model call status, latency, token usage, and model
  name are persisted as audit metrics without prompts or hidden reasoning.
  `GET /v1/runs/{run_id}/evaluation` returns verification and agent/provider
  metrics, scoped to the authenticated workspace. Optional
  `AGENT_INPUT_COST_PER_MILLION_USD` and `AGENT_OUTPUT_COST_PER_MILLION_USD`
  yield a flat-rate cost estimate; absent rates or usage produce `null`, not
  zero. Actual billed model cost remains unknown. Estimates do not account for
  cached-token discounts or provider billing adjustments.

Example explicit memory request:

```json
{
  "prompt": "Use the selected record to prepare the next workflow",
  "memory_run_id": "<verified-source-run-id>",
  "memory_bindings": {"record_id": "steps.lookup.id"},
  "inputs": {}
}
```

## Verification and remaining development

The test suite exercises actual persisted orchestration with isolated SQLite
sessions and simulated provider/model calls: receipt persistence before review,
resume without duplicate writes, unknown-outcome blocking, and final-verification
failure. It also covers graph references, verifier evidence validation, memory
isolation, API isolation, and metrics. PostgreSQL lock contention and release are
covered by an integration test using `AURA_TEST_POSTGRES_URL`; the Python CI job
provides a PostgreSQL service. Local runs without that URL skip this one test.

This is the first increment across the six development areas, not completion of
all future agent work. The outcome verifier judges existing connector evidence;
provider-specific read-back/reconciliation operations are still needed when a
receipt cannot establish the requested result. Automatic semantic replanning of
failed plans is not introduced. Changed actions still need a newly reviewed
plan; unknown external outcomes require reconciliation before a new action.
Memory is explicit selection, not semantic retrieval or automatic preference
learning. Agent metrics support evaluation but do not yet supply a benchmark
corpus or a dashboard.

Operational limits: advisory locks require PostgreSQL and one extra connection
per active run. They assume a live dedicated database session (not a transaction
pooler). A network partition losing the lock session is not a fencing protocol;
provider-supported idempotency and reconciliation remain necessary for stronger
exactly-once guarantees. Metrics are persisted after the task returns, so a hard
process kill can lose the last task's model metrics. The verifier adds model
latency and can pause previously auto-accepted workflows when evidence is weak.
