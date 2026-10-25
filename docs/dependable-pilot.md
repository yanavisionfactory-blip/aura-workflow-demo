# Dependable AURA pilot

Use **KPI dashboard pilot** on the AURA home screen. Its sample Plantéa figures are illustrative; replace them with Mason's actual snapshot before assessing business outcomes. The fixed template creates a new Google workbook with dashboard, feedback and product brief tabs in one write. Independent reads check all input cells, formulas, numeric formats, feedback, AOV and conversion rate. Target and actual use the same selected denominator; zero denominators produce “n/a”. User text is stored literally, never as a formula.

Before Start, AURA verifies the selected connection, its account identity, required operations and existing destinations. The account is checked again at approval and execution. A changed account requires renewed review. Connector-side permission failures still pause execution; a successful preflight cannot guarantee that a provider stays available.

The runtime checkpoints write receipts before verification. A restart verifies the saved receipt. An unknown write outcome requires reconciliation; it must not be blindly retried. This avoids a duplicate from an automatic retry, but intentionally starting a separate workflow creates a separate workbook.

## Production authentication

Pipedream development accounts and production accounts are separate. Before changing the default, set `PIPEDREAM_LEGACY_ENVIRONMENT=development` on the API and worker. Existing unpinned references keep using their original environment; new/reconnected references store an explicit environment. Signed authorization state preserves the environment through the connection callback.

Enable production access in Pipedream billing first, then set `PIPEDREAM_ENVIRONMENT=production` on the API and worker. Verify a new customer account after consent. Existing development connections continue to work for personal testing; they are not migrated into production credentials automatically. To migrate an existing connection, disconnect/reconnect it with the new default after the owner approves. Never copy customer credentials into GitHub issues, logs, or chat.

## Support access

**Get help with this run** requires explicit consent and creates a 30-minute, revocable read-only link. It contains only run status, known operation names and receipt/verification presence. Prompts, arguments, outputs, account identities, arbitrary error messages and credentials are excluded. The backend stores a token hash, enforces expiry and tenancy, checks that the granting member is still authorized, and audits reads and revocations. Possession of the link grants its limited access; share it only with the intended support person. No support endpoint can execute or resume a run. The customer resumes through their normal authenticated AURA UI.

## Release and model gates

The backend release requires successful Python control-plane CI (which includes frontend tests/build and complete workflow regression tests) on the exact main-branch SHA. Evidence is retained in Actions. A health-only Railway canary deploys first and cannot migrate, dispatch or serve customer requests. Its readiness must report the exact stamped SHA and canary mode before deploying the worker and API. API readiness must then report the same SHA in production mode. Failed benchmarks return a failing exit code.

Tests include the complete KPI execution, resume from a saved workbook receipt, unknown-write recovery, expired authentication, wrong tenants/accounts, destination denial, revoked support links, timeouts and formula mismatches. Simulated provider tests are not a substitute for a live, separately authorized customer-account pilot. Require a live pilot before claiming production readiness for a new connector.

Do not change the production model based on preference. The offline comparison runner sends the same eight synthetic cases to both models and records pass/fail and latency without changing routing. It requires both provider keys in the process's secure environment before making any request:

```sh
cd backend
python -m app.model_evaluation --openai-model "$OPENAI_MODEL" --anthropic-model "$ANTHROPIC_MODEL" --repeats 3 --report model-comparison.json
```

This qualification checks KPI arithmetic and safe decisions. It does not prove that a new model integrates correctly with AURA's planner, tools or real customer accounts. Any model change must also pass the same runtime and live-connector tests. Claude connection, paid production entitlement, live customer consent and the measured model comparison remain external verification steps, not claims implied by deploying this code.
