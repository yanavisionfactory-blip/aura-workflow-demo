"""Deploy a tested release, resuming a canary and honoring Railway pauses."""
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SERVICES = (
    ("canary", "897cf632-57e3-4c53-978a-63c8c308bc02"),
    ("worker", "33c7fb6a-2fcd-446b-b8ff-969f6bcb93fd"),
    ("API", "4dae3f58-70dd-44e4-804f-e21441c4ec41"),
)
HOSTS = {
    "canary": "https://aura-recovery-canary-production.up.railway.app",
    "API": "https://impartial-emotion-production-49d4.up.railway.app",
}
PENDING = {"WAITING", "QUEUED", "INITIALIZING", "BUILDING", "DEPLOYING"}
PAUSED = "Deploys have been paused temporarily"


def fetch_ready(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.load(response)


class Release:
    def __init__(self, project, environment, sha, backend, *, run=subprocess.run,
                 clock=time.monotonic, sleep=time.sleep, read_ready=fetch_ready,
                 timeout_seconds=7200):
        if not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ValueError("A full release commit SHA is required")
        self.project, self.environment, self.sha = project, environment, sha
        self.backend = str(Path(backend).resolve())
        self.run, self.clock, self.sleep, self.read_ready = run, clock, sleep, read_ready
        self.deadline = clock() + timeout_seconds

    def pause(self, seconds=15):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError("Backend release exceeded its two-hour recovery window")
        self.sleep(min(seconds, remaining))

    def deployments(self, service):
        result = self.run([
            "railway", "deployment", "list", "--project", self.project,
            "--environment", self.environment, "--service", service, "--json",
        ], check=True, capture_output=True, text=True, timeout=60)
        data = json.loads(result.stdout)
        return data if isinstance(data, list) else data["deployments"]

    def upload(self, name, service):
        while self.clock() < self.deadline:
            result = self.run([
                "railway", "up", self.backend, "--detach", "--project", self.project,
                "--environment", self.environment, "--service", service,
                "--message", f"AURA verified release {self.sha} ({name})",
            ], check=False, capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                return
            # Only this explicit rejection proves no deployment was accepted.
            # Never retry an ambiguous upload error and risk duplicate deploys.
            if PAUSED not in (result.stdout or "") + (result.stderr or ""):
                raise RuntimeError(f"{name}: Railway upload failed (exit {result.returncode})")
            print(f"{name}: Railway deployments are paused; retrying in 60 seconds", flush=True)
            self.pause(60)
        raise TimeoutError("Railway remained paused for the release recovery window")

    def wait_for_deployment(self, name, service, baseline, deployment_id=None):
        while self.clock() < self.deadline:
            items = self.deployments(service)
            if deployment_id is None:
                fresh = [item for item in items if item["id"] not in baseline]
                if fresh:
                    deployment_id = fresh[0]["id"]
            if deployment_id:
                deployment = next((item for item in items if item["id"] == deployment_id), None)
                if deployment is None:
                    raise RuntimeError(f"{name}: selected deployment is not in this service")
                status = deployment["status"]
                print(f"{name}: {deployment_id} {status}", flush=True)
                if status == "SUCCESS":
                    return deployment_id
                if status not in PENDING:
                    raise RuntimeError(f"{name}: deployment stopped with {status}")
            self.pause()
        raise TimeoutError(f"{name}: deployment exceeded the release recovery window")

    def verify_ready(self, name):
        deadline = min(self.deadline, self.clock() + 120)
        while self.clock() < deadline:
            try:
                ready = self.read_ready(HOSTS[name] + "/ready")
                if (ready.get("status") == "ready" and ready.get("release_sha") == self.sha
                        and ready.get("canary") is (name == "canary")):
                    return
            except (urllib.error.URLError, TimeoutError, ValueError):
                pass
            self.pause()
        raise RuntimeError(f"{name}: exact release readiness did not pass")

    def deploy(self, resume_canary=None, summary_path=None):
        if resume_canary:
            uuid.UUID(resume_canary)
        for name, service in SERVICES:
            if name == "canary" and resume_canary:
                # Resume only the explicit deployment in the canary service.
                # The live /ready response must still prove this release and mode.
                deployment_id = self.wait_for_deployment(name, service, set(), resume_canary)
            else:
                baseline = {item["id"] for item in self.deployments(service)}
                self.upload(name, service)
                deployment_id = self.wait_for_deployment(name, service, baseline)
            if name in HOSTS:
                self.verify_ready(name)
            if summary_path:
                with open(summary_path, "a") as summary:
                    summary.write(f"- {name}: `{deployment_id}` SUCCESS; source `{self.sha}`\n")
        print("Canary, worker and API release completed; exact API readiness passed.", flush=True)


if __name__ == "__main__":
    Release(
        os.environ["RAILWAY_PROJECT"], os.environ["RAILWAY_ENVIRONMENT"],
        os.environ["RELEASE_SHA"], "backend",
    ).deploy(os.environ.get("RESUME_CANARY_DEPLOYMENT_ID") or None,
             os.environ.get("GITHUB_STEP_SUMMARY"))
