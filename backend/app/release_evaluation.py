"""Dedicated-account connector conformance runner; never use customer credentials.

python -m app.release_evaluation --fixtures fixtures.json --ledger ledger.json --report report.json --allow-writes
A persistent ledger is mandatory. Restarting rechecks saved receipts; an unknown
write outcome stops for reconciliation instead of repeating the action.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from jsonschema import Draft202012Validator
from .native_connectors import native_manifest
from .operation_contracts import output_errors
from .outcome_checks import build_outcome_check, evaluate_outcome_check
from .extended_outcomes import observe_check
from .providers import ProviderExecutor, verify_oauth_credentials


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


async def evaluate(fixtures, ledger_path, report_path, allow_writes=False):
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    report = {"release": os.getenv("GITHUB_SHA", os.getenv("RAILWAY_GIT_COMMIT_SHA")),
              "evaluated_at": datetime.now(timezone.utc).isoformat(), "cases": []}
    for fixture in fixtures:
        row = {"case": fixture["id"], "operation": fixture["operation"], "status": "failed"}
        try:
            if fixture.get("dedicated_test_account") is not True:
                raise ValueError("Dedicated test account declaration required")
            manifest = native_manifest(fixture["connector"])
            module = next(item for item in manifest["capabilities"] if item["name"] == fixture["operation"])
            row["contract_hash"] = module["reliability"]["hash"]
            credentials = json.loads(os.environ[fixture["credentials_env"]])
            verification = await verify_oauth_credentials(fixture["connector"], credentials)
            identity = verification.get("identity", {})
            expected = fixture["expected_account_id"]
            if not expected or expected not in {identity.get("id"), identity.get("email")}:
                raise ValueError("Fixture account identity mismatch")
            arguments = fixture["arguments"]
            Draft202012Validator(module["input_schema"]).validate(arguments)
            write = module["permission_scope"] != "read"
            if write and not allow_writes:
                raise ValueError("Live fixture writes require --allow-writes")
            executor = ProviderExecutor(credentials, manifest.get("base_url", "provider-managed"),
                provider_kind="oauth", timeout_seconds=30, capability_manifest=manifest)
            saved = ledger.get(fixture["id"])
            import hashlib
            fingerprint = hashlib.sha256(json.dumps({"account": expected, "operation": fixture["operation"],
                "arguments": arguments, "contract": row["contract_hash"]}, sort_keys=True).encode()).hexdigest()
            if saved and saved.get("fingerprint") != fingerprint:
                raise ValueError("Fixture changed; use a new case id, preserving the old ledger")
            lost_response_resume = bool(saved and "witness_receipt" in saved)
            if saved and "receipt" not in saved and not lost_response_resume:
                raise ValueError("Unknown previous outcome; reconcile provider state before continuing")
            if saved:
                receipt = saved["witness_receipt"] if lost_response_resume else saved["receipt"]
            else:
                ledger[fixture["id"]] = {"fingerprint": fingerprint, "state": "dispatched"}
                save(ledger_path, ledger)
                receipt = await asyncio.wait_for(executor.execute(fixture["operation"], arguments), 30)
                if fixture.get("simulate_lost_response") and write:
                    # Test observer keeps a witness. The execution ledger has no receipt;
                    # a subsequent invocation must reconcile by reading, never write again.
                    ledger[fixture["id"]]["witness_receipt"] = receipt
                    save(ledger_path, ledger)
                    raise TimeoutError("Injected response loss after dedicated fixture write")
                ledger[fixture["id"]]["provider_executed"] = True
                ledger[fixture["id"]]["receipt"] = receipt
                save(ledger_path, ledger)  # Save before schema checks or read-back.
            if output_errors(fixture["operation"], receipt):
                raise ValueError("Receipt violates the connector output contract")
            if write:
                check = build_outcome_check(fixture["operation"], arguments, receipt)
                if not check or not check.resource_id:
                    raise ValueError("Operation has no complete deterministic outcome check")
                observed = await asyncio.wait_for(observe_check(executor, check), 30)
                outcome = evaluate_outcome_check(check, observed)
                if outcome.get("status") != "verified":
                    raise ValueError("Provider outcome was not verified")
            scenarios = ["lost_response"] if lost_response_resume else ["receipt_resume"] if saved else ["execute"]
            if saved and saved.get("provider_executed") and not lost_response_resume:
                scenarios.append("execute")
            if write:
                scenarios.append("read_back")
            row.update(status="passed", resumed_from_receipt=bool(saved) and not lost_response_resume, write=write,
                provider_account_id=expected, passed_scenarios=scenarios)
        except Exception as exc:
            # Diagnostics never include raw credentials, arguments or provider content.
            row["error_type"] = type(exc).__name__
        report["cases"].append(row)
        save(report_path, report)
    report["passed"] = bool(report["cases"]) and all(row["status"] == "passed" for row in report["cases"])
    save(report_path, report)
    return report["passed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-writes", action="store_true")
    args = parser.parse_args()
    fixtures = json.loads(args.fixtures.read_text())
    ids = [fixture["id"] for fixture in fixtures]
    if len(ids) != len(set(ids)):
        parser.error("Fixture case ids must be unique")
    # One runner per ledger. A local process lock prevents concurrent fixture writes.
    import fcntl
    with args.ledger.with_suffix(args.ledger.suffix + ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        success = asyncio.run(evaluate(fixtures, args.ledger, args.report, args.allow_writes))
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
