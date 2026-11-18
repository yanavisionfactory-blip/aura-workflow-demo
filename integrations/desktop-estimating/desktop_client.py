"""Outbound-only transport for the packaged Windows helper. No arbitrary commands."""
import base64
import json
import re
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from aura_estimator import bounded_operation
from estimate_core import Store, get_estimate
from estimating_contract import DEFINITIONS, PROTOCOL, ReportRequest

API_ORIGIN = "https://impartial-emotion-production-49d4.up.railway.app"
ROOT = "/v1/desktop-estimating"


class ClientError(RuntimeError):
    def __init__(self, message, status=None):
        self.status = status
        super().__init__(message)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def pairing_code(value):
    value = value.strip()
    if value.startswith("aura-estimator:"):
        url = urlsplit(value)
        query = parse_qs(url.query, strict_parsing=True)
        if url.scheme != "aura-estimator" or url.netloc != "pair" or url.path not in {"", "/"} or url.fragment or set(query) != {"code"} or len(query["code"]) != 1:
            raise ValueError("Use the pairing link provided by AURA")
        value = query["code"][0]
    parts = value.split(".")
    if len(parts) != 3 or not re.fullmatch(r"[A-Za-z0-9_-]{43}", parts[2]):
        raise ValueError("Copy a fresh pairing code from AURA")
    if str(UUID(parts[0])) != parts[0] or str(UUID(parts[1])) != parts[1]:
        raise ValueError("Invalid pairing workspace")
    return value


class DesktopClient:
    def __init__(self, config, config_path, *, execute=bounded_operation, opener=None):
        self.config, self.config_path, self.execute = config, Path(config_path), execute
        self.opener = opener or build_opener(NoRedirect())
        self.operation_lock = threading.Lock()

    def request(self, path, payload, *, authenticated=False):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.config["device_token"]
        request = Request(API_ORIGIN + ROOT + path, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read(17_000_001)
                if len(raw) > 17_000_000:
                    raise ClientError("AURA returned an oversized response")
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ClientError("AURA returned an invalid response")
                return value
        except HTTPError as exc:
            # Only fixed application diagnostics; never include request bodies or credentials.
            try:
                detail = json.loads(exc.read(2000)).get("detail")
            except (ValueError, AttributeError):
                detail = None
            message = detail[:300] if isinstance(detail, str) else "AURA could not complete this request"
            raise ClientError(message, exc.code) from None
        except (URLError, TimeoutError, OSError):
            raise ClientError("AURA is unreachable. Check your internet connection; the helper will retry.") from None

    def info(self, code):
        return self.request("/pairings/info", {"code": pairing_code(code)})

    def pair(self, code):
        code = pairing_code(code)
        if self.config.get("workspace_id") not in {None, code.split(".")[0]}:
            raise ClientError("This helper is already paired to another workspace. Disconnect it there before changing workspace.")
        if not self.operation_lock.acquire(blocking=False):
            raise ClientError("The desktop apps are busy. Retry after the current task finishes.")
        try:
            status = self.execute(self.config, "status", {})
        finally:
            self.operation_lock.release()
        result = self.request("/pairings/claim", {
            "code": code, "instance_id": self.config["instance_id"],
            "device_token": self.config["device_token"], "applications": status["applications"],
        })
        if result.get("status") != "verified" or result.get("workspace_id") != code.split(".")[0]:
            raise ClientError("AURA did not verify the requested workspace")
        self.config["workspace_id"] = result["workspace_id"]
        self.config["workspace_name"] = result["workspace_name"]
        self.save()
        return result

    def save(self):
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.config), encoding="utf-8")
        temporary.replace(self.config_path)

    @property
    def device_path(self):
        return f"/devices/{UUID(self.config['workspace_id'])}/{UUID(self.config['instance_id'])}"

    def poll(self, busy=False):
        return self.request(self.device_path + "/poll", {"busy": busy}, authenticated=True).get("command")

    def perform(self, command):
        if not isinstance(command, dict) or set(command) != {"id", "operation", "arguments", "expires_at"}:
            raise ClientError("AURA sent an unsupported command")
        if not re.fullmatch(r"[a-f0-9]{32}", command["id"]) or command["expires_at"] <= time.time():
            raise ClientError("The command expired before execution")
        operation, arguments = command["operation"], command["arguments"]
        if operation == "download":
            request = ReportRequest.model_validate(arguments)
            store = Store(self.config["data_folder"])
            get_estimate(store, request.report_id)
            path = store.path("Reports", request.report_id, ".xlsx")
            if path.stat().st_size > 12_000_000:
                raise ClientError("The workbook is too large")
            return {"ok": True, "workbook_base64": base64.b64encode(path.read_bytes()).decode()}
        if operation == "status":
            if arguments != {}:
                raise ClientError("Invalid application check")
        elif operation in DEFINITIONS:
            arguments = DEFINITIONS[operation][1].model_validate(arguments).model_dump(mode="json")
        else:
            raise ClientError("AURA requested an unsupported action")
        with self.operation_lock:
            value = self.execute(self.config, operation, arguments)
        return {"ok": True, "value": {"protocol": PROTOCOL, "instance_id": self.config["instance_id"],
                **(value if operation == "status" else {"result": value})}}

    def send_result(self, command_id, result):
        if not re.fullmatch(r"[a-f0-9]{32}", command_id):
            raise ClientError("Invalid command identity")
        return self.request(self.device_path + "/results/" + command_id, result, authenticated=True)
