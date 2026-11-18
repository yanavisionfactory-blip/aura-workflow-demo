import importlib
import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.fixture
def client_module(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "backend" / "app"))
    monkeypatch.syspath_prepend(str(root / "integrations" / "desktop-estimating"))
    return importlib.import_module("desktop_client")


def test_pairing_uri_accepts_only_the_fixed_protocol_and_opaque_code(client_module):
    code = f"{uuid4()}.{uuid4()}." + "a" * 43
    assert client_module.pairing_code("aura-estimator://pair?code=" + code) == code
    for value in ["https://evil.test/?code=" + code,
                  "aura-estimator://pair?code=" + code + "&server=https://evil.test",
                  "aura-estimator://evil?code=" + code,
                  "aura-estimator://pair?code=" + code + "#secret", "invalid"]:
        with pytest.raises(ValueError):
            client_module.pairing_code(value)


def test_helper_executes_only_schema_checked_operations(client_module, tmp_path):
    calls = []
    def execute(config, operation, arguments):
        calls.append((operation, arguments))
        return {"rate_books": ["Approved-Rates.xlsx"]}
    instance = str(uuid4())
    client = client_module.DesktopClient({"instance_id": instance, "data_folder": str(tmp_path)},
                                        tmp_path / "config.json", execute=execute)
    command = {"id": "a" * 32, "expires_at": time.time() + 60,
               "operation": "excel.ratebooks.list", "arguments": {}}
    result = client.perform(command)
    assert result["value"]["instance_id"] == instance
    assert result["value"]["result"]["rate_books"] == ["Approved-Rates.xlsx"]
    for invalid in [{**command, "operation": "shell.exec"},
                    {**command, "arguments": {"path": "C:/private"}},
                    {**command, "expires_at": 0},
                    {**command, "operation": "download", "arguments": {"report_id": "../../private"}}]:
        with pytest.raises((ValueError, client_module.ClientError)):
            client.perform(invalid)
    assert len(calls) == 1


def test_pair_claim_probes_real_adapters_and_preserves_identity_on_retry(client_module, tmp_path, monkeypatch):
    code = f"{uuid4()}.{uuid4()}." + "a" * 43
    config = {"instance_id": str(uuid4()), "device_token": "test-device-token-01234567890123456789"}
    apps = {"excel-desktop": {"available": True, "version": "16"}}
    def execute(config, operation, arguments):
        assert operation == "status" and arguments == {"providers": ["excel-desktop"]}
        return {"applications": apps}
    client = client_module.DesktopClient(config, tmp_path / "config.json", execute=execute)
    payloads = []
    def claim(path, payload):
        payloads.append(payload)
        return {"status": "verified", "workspace_id": code.split(".")[0], "workspace_name": "Test", "provider": "excel-desktop"}
    monkeypatch.setattr(client, "request", claim)
    client.pair(code, "excel-desktop")
    client.pair(code, "excel-desktop")
    assert payloads[0] == payloads[1]
    assert payloads[0]["applications"] == apps
    assert payloads[0]["pairing_protocol"] == 2
    assert client.config["authorized_providers"] == ["excel-desktop"]
    assert client.config_path.exists()


@pytest.mark.parametrize("provider", ["planswift", "excel-desktop"])
def test_application_probe_never_opens_the_other_app(client_module, provider):
    windows = importlib.import_module("windows_apps")
    calls = []
    def planswift(progid):
        calls.append("planswift")
        assert provider == "planswift", "Excel connection must not open PlanSwift"
        return SimpleNamespace(CurrentVersion="12", IsLoaded=True)
    def excel(progid):
        calls.append("excel-desktop")
        assert provider == "excel-desktop", "PlanSwift connection must not open Excel"
        return SimpleNamespace(Version="16", Quit=lambda: None)
    adapter = windows.WindowsApps({}, dispatch=planswift, dispatch_ex=excel)
    assert adapter.status([provider]) == {provider: {"available": True, "version": "12" if provider == "planswift" else "16"}}
    assert calls == [provider]


def test_helper_retries_a_receipt_without_repeating_the_action(client_module):
    app = importlib.import_module("desktop_app")
    stop = threading.Event()
    class QuickStop:
        def is_set(self):
            return stop.is_set()
        def wait(self, _):
            return stop.wait(0.001)
    class Client:
        polled = executed = sent = 0
        def __init__(self):
            self.config = {"workspace_name": "Test"}
        def poll(self, busy=False):
            self.polled += 1
            return {"id": "a" * 32, "operation": "excel.estimate.create"} if self.polled == 1 else None
        def perform(self, command):
            self.executed += 1
            return {"ok": True}
        def send_result(self, command_id, result):
            self.sent += 1
            if self.sent == 1:
                raise client_module.ClientError("Synthetic lost acknowledgement")
            stop.set()
    client = Client()
    app.serve(client, QuickStop(), queue.Queue())
    assert client.executed == 1
    assert client.sent == 2
