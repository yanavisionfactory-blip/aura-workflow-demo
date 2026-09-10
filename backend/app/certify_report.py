"""Sign completed live release evidence for one exact deployment connection.

The signing key belongs only to the trusted certification environment and API.
A successful test runner invocation alone is never sufficient for certification.
"""
import argparse
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .assurance import canonical, SCENARIOS
from .native_connectors import native_manifest


def build_attestation(reports, scope, key):
    module = next(item for item in native_manifest(scope["connector"])["capabilities"] if item["name"] == scope["operation"])
    expected = SCENARIOS["read" if module["permission_scope"] == "read" else "write"]
    passed = set()
    account_ids = set()
    releases = set()
    for report in reports:
        if not report.get("passed"):
            raise ValueError("A release report contains failures")
        releases.add(report.get("release"))
        for case in report.get("cases", []):
            if case.get("operation") != scope["operation"]:
                continue
            if case.get("contract_hash") != module["reliability"]["hash"] or case.get("status") != "passed":
                raise ValueError("Case does not match the current contract")
            account_ids.add(case.get("provider_account_id"))
            passed.update(case.get("passed_scenarios", []))
    if not expected <= passed or len(account_ids) != 1 or None in account_ids or len(releases) != 1 or None in releases:
        raise ValueError("Live scenario, provider account or release evidence is incomplete")
    if len(key) < 32:
        raise ValueError("Trusted signing key is not configured")
    now = datetime.now(timezone.utc)
    report = {**scope, "contract_hash": module["reliability"]["hash"], "scenarios": {name: "passed" for name in passed},
        "provider_account_id": next(iter(account_ids)), "release_sha": next(iter(releases)),
        "dedicated_test_account": True, "issued_at": now.isoformat(), "expires_at": (now + timedelta(days=7)).isoformat(),
        "evidence_digest": hashlib.sha256(canonical(reports)).hexdigest()}
    return {"report": report, "signature": hmac.new(key.encode(), canonical(report), hashlib.sha256).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", nargs="+", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_attestation([json.loads(path.read_text()) for path in args.reports], json.loads(args.scope.read_text()), os.environ.get("CERTIFICATION_SIGNING_KEY", ""))
    args.output.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
