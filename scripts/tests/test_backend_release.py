import contextlib
import io
import json
import subprocess
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy_backend_release import PAUSED, SERVICES, Release

SHA = "a" * 40
CANARY_ID = "86f4516e-1d55-41d7-91fb-20153fe2b03a"


class Clock:
    now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.run = Mock()
        self.ready = Mock()
        self.release = Release("project", "production", SHA, "backend", run=self.run,
                               clock=self.clock, sleep=self.clock.sleep, read_ready=self.ready)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_explicit_pause_is_retried_without_changing_target(self):
        self.run.side_effect = [subprocess.CompletedProcess([], 1, "", PAUSED),
                                subprocess.CompletedProcess([], 0, "accepted", "")]
        self.release.upload("worker", SERVICES[1][1])
        self.assertEqual(self.clock.now, 60)
        self.assertEqual(self.run.call_args_list[0], self.run.call_args_list[1])

    def test_ambiguous_upload_failure_is_never_retried(self):
        self.run.return_value = subprocess.CompletedProcess([], 1, "", "connection reset")
        with self.assertRaisesRegex(RuntimeError, "upload failed"):
            self.release.upload("worker", SERVICES[1][1])
        self.run.assert_called_once()

    def test_pause_wait_is_bounded(self):
        self.release.deadline = 60
        self.run.return_value = subprocess.CompletedProcess([], 1, PAUSED, "")
        with self.assertRaises(TimeoutError):
            self.release.upload("worker", SERVICES[1][1])
        self.assertEqual(self.clock.now, 60)
        self.run.assert_called_once()

    def test_selected_canary_is_resumed_without_another_upload(self):
        with patch.object(self.release, "wait_for_deployment", return_value=CANARY_ID) as wait, \
             patch.object(self.release, "deployments", return_value=[]) as deployments, \
             patch.object(self.release, "upload") as upload, \
             patch.object(self.release, "verify_ready") as ready:
            self.release.deploy(CANARY_ID)
        self.assertEqual(wait.call_args_list[0].args, ("canary", SERVICES[0][1], set(), CANARY_ID))
        self.assertEqual([call.args[0] for call in upload.call_args_list], ["worker", "API"])
        self.assertEqual(deployments.call_count, 2)
        self.assertEqual([call.args[0] for call in ready.call_args_list], ["canary", "API"])

    def test_missing_resume_id_does_not_fall_back_to_another_deployment(self):
        with (
            patch.object(self.release, "deployments", return_value=[{"id": "other", "status": "SUCCESS"}]),
            self.assertRaisesRegex(RuntimeError, "not in this service"),
        ):
            self.release.wait_for_deployment("canary", SERVICES[0][1], set(), CANARY_ID)

    def test_wrong_canary_release_stops_before_worker_upload(self):
        self.ready.return_value = {"status": "ready", "release_sha": "b" * 40, "canary": True}
        with (
            patch.object(self.release, "wait_for_deployment", return_value=CANARY_ID),
            patch.object(self.release, "upload") as upload,
            self.assertRaisesRegex(RuntimeError, "exact release readiness"),
        ):
            self.release.deploy(CANARY_ID)
        upload.assert_not_called()

    def test_wrong_canary_mode_is_rejected(self):
        self.ready.return_value = {"status": "ready", "release_sha": SHA, "canary": False}
        with self.assertRaisesRegex(RuntimeError, "exact release readiness"):
            self.release.verify_ready("canary")

    def test_readiness_waits_for_rollout_propagation(self):
        self.ready.side_effect = [urllib.error.URLError("warming up"),
                                 {"status": "ready", "release_sha": "b" * 40, "canary": True},
                                 {"status": "ready", "release_sha": SHA, "canary": True}]
        self.release.verify_ready("canary")
        self.assertEqual(self.clock.now, 30)

    def test_wait_tracks_same_deployment_when_another_appears(self):
        with patch.object(self.release, "deployments", side_effect=[
            [{"id": "old", "status": "SUCCESS"}, {"id": "new", "status": "BUILDING"}],
            [{"id": "other", "status": "SUCCESS"}, {"id": "new", "status": "SUCCESS"}],
        ]):
            self.assertEqual(self.release.wait_for_deployment("API", SERVICES[2][1], {"old"}), "new")

    def test_terminal_failure_is_not_accepted(self):
        with (
            patch.object(self.release, "deployments", return_value=[{"id": CANARY_ID, "status": "FAILED"}]),
            self.assertRaisesRegex(RuntimeError, "stopped with FAILED"),
        ):
            self.release.wait_for_deployment("canary", SERVICES[0][1], set(), CANARY_ID)

    def test_pending_deployment_wait_is_bounded(self):
        self.release.deadline = 30
        with (
            patch.object(self.release, "deployments", return_value=[{"id": CANARY_ID, "status": "BUILDING"}]),
            self.assertRaises(TimeoutError),
        ):
            self.release.wait_for_deployment("canary", SERVICES[0][1], set(), CANARY_ID)
        self.assertEqual(self.clock.now, 30)

    def test_list_uses_explicit_project_environment_and_service(self):
        self.run.return_value = subprocess.CompletedProcess([], 0, json.dumps({"deployments": []}))
        self.assertEqual(self.release.deployments("service"), [])
        args = self.run.call_args.args[0]
        self.assertEqual(args, ["railway", "deployment", "list", "--project", "project",
                                "--environment", "production", "--service", "service", "--json"])

    def test_invalid_release_and_resume_values_are_rejected(self):
        with self.assertRaises(ValueError):
            Release("project", "production", "main", "backend")
        with self.assertRaises(ValueError):
            self.release.deploy("not-a-deployment-id")
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
