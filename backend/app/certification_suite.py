"""Run execute/read-back/receipt-resume/response-loss checks for dedicated fixtures.

The suite consumes explicitly configured test accounts; it never discovers or
borrows customer credentials. Missing fixtures fail readiness rather than skip.
"""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
from .release_evaluation import evaluate, save
from .native_connectors import native_manifest


async def run_suite(fixtures, directory, *, allow_writes=False):
    directory.mkdir(parents=True, exist_ok=True)
    if len({f["id"] for f in fixtures}) != len(fixtures):
        raise ValueError("Fixture ids must be unique")
    rows = []
    for fixture in fixtures:
        if fixture.get("dedicated_test_account") is not True:
            raise ValueError("Every fixture must explicitly designate a dedicated test account")
        import hashlib
        name = hashlib.sha256(fixture["id"].encode()).hexdigest()[:24]
        module = next(m for m in native_manifest(fixture["connector"])["capabilities"] if m["name"] == fixture["operation"])
        write = module["permission_scope"] != "read"
        phases = ["execute", "receipt_resume"] + (["lost_response_injection", "lost_response_reconcile"] if write else [])
        evidence = []
        for phase in phases:
            case = copy.deepcopy(fixture)
            lost = phase.startswith("lost_response")
            case["id"] = fixture["id"] + (":lost-response" if lost else ":normal")
            case["simulate_lost_response"] = lost
            ledger = directory / (name + ("-lost.json" if lost else "-normal.json"))
            report = directory / f"{name}-{phase}.json"
            # Preserve the initial execution evidence across interrupted suite invocations.
            if phase == "execute" and report.exists() and json.loads(report.read_text()).get("passed"):
                evidence.append(str(report)); continue
            passed = await evaluate([case], ledger, report, allow_writes)
            if phase == "lost_response_injection":
                saved = json.loads(ledger.read_text()) if ledger.exists() else {}
                if "witness_receipt" not in saved.get(case["id"], {}):
                    break
                continue
            if not passed:
                break
            evidence.append(str(report))
        scenarios = {scenario for path in evidence for row in json.loads(Path(path).read_text())["cases"] for scenario in row.get("passed_scenarios", [])}
        required = {"execute", "receipt_resume"} | ({"read_back", "lost_response"} if write else set())
        rows.append({"fixture": fixture["id"], "connector": fixture["connector"], "operation": fixture["operation"],
            "passed": required <= scenarios, "scenarios": sorted(scenarios), "reports": evidence,
            "missing_scenarios": sorted(required - scenarios)})
    connectors = {f["connector"] for f in fixtures}
    covered = {(r["connector"], r["operation"]) for r in rows if r["passed"]}
    missing = [{"connector": slug, "operation": m["name"]} for slug in sorted(connectors)
        for m in native_manifest(slug)["capabilities"] if m["permission_scope"] != "read" and (slug,m["name"]) not in covered]
    return {"passed": bool(rows) and all(r["passed"] for r in rows) and not missing,
        "operation_results": rows, "uncertified_writes": missing,
        "scope": "dedicated_provider_accounts", "release": os.getenv("GITHUB_SHA", os.getenv("RAILWAY_GIT_COMMIT_SHA"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--ledger-directory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-writes", action="store_true")
    args = parser.parse_args()
    import fcntl
    args.ledger_directory.mkdir(parents=True, exist_ok=True)
    with (args.ledger_directory / "suite.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = asyncio.run(run_suite(json.loads(args.fixtures.read_text()), args.ledger_directory, allow_writes=args.allow_writes))
    save(args.report, result)
    print(json.dumps({"passed": result["passed"], "operations": len(result["operation_results"]), "uncertified_writes": len(result["uncertified_writes"])}))
    raise SystemExit(0 if result["passed"] else 1)

if __name__ == "__main__":
    main()
