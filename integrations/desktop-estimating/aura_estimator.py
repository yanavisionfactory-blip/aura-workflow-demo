"""Authenticated Windows bridge. Bind to loopback behind an HTTPS tunnel only."""
import argparse
import hmac
import json
import multiprocessing
import os
import queue
import sys
import threading
from pathlib import Path

from estimate_core import Store, create_estimate, get_estimate, read_rates
from estimating_contract import DEFINITIONS, PROTOCOL
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse


def run_operation(config, operation, arguments, adapter=None):
    from windows_apps import WindowsApps
    adapter = adapter or WindowsApps(config)
    store = Store(config["data_folder"])
    if operation == "status":
        return {"applications": adapter.status()}
    request = DEFINITIONS[operation][1].model_validate(arguments).model_dump(mode="json")
    if operation == "planswift.job.read":
        source, rows = adapter.takeoff(request)
        return store.save_snapshot("takeoff", source, rows)
    if operation == "excel.ratebooks.list":
        names = sorted(path.name for path in (store.root / "Rates").glob("*.xlsx") if not path.is_symlink())
        if len(names) > 5000:
            raise ValueError("Too many rate books in the configured folder")
        return {"rate_books": names}
    if operation == "excel.rates.read":
        return read_rates(store, request["rate_book"], request["as_of"])
    if operation == "excel.estimate.create":
        return create_estimate(store, request, adapter.recalculate)
    if operation == "excel.estimate.get":
        return get_estimate(store, request["report_id"])
    raise ValueError("Unsupported operation")


def worker(config, operation, arguments, output):
    import pythoncom
    pythoncom.CoInitialize()
    try:
        output.put({"ok": True, "value": run_operation(config, operation, arguments)})
    except Exception as exc:  # noqa: BLE001 -- isolate all COM and workbook failures at the process boundary
        # Local diagnosis contains no request body or credential. Cloud callers get a fixed error.
        if sys.stdout is not None:
            print(f"{operation} failed: {type(exc).__name__}: {str(exc)[:400]}", flush=True)
        output.put({"ok": False})
    finally:
        pythoncom.CoUninitialize()


def bounded_operation(config, operation, arguments):
    ctx = multiprocessing.get_context("spawn")
    output = ctx.Queue(maxsize=1)
    process = ctx.Process(target=worker, args=(config, operation, arguments, output))
    process.start()
    try:
        result = output.get(timeout=90)
        if not result.get("ok"):
            raise ValueError("Check the connector console and source inputs")
        return result["value"]
    except queue.Empty:
        raise TimeoutError("The desktop application did not respond in 90 seconds") from None
    finally:
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
        output.close()


def create_app(config, execute=bounded_operation):
    if len(str(config.get("connection_key", ""))) < 32:
        raise ValueError("A connection key of at least 32 characters is required")
    app = FastAPI(title="AURA PlanSwift and Excel connector", docs_url=None, redoc_url=None, openapi_url=None)
    lock = threading.Lock()
    store = Store(config["data_folder"])

    @app.middleware("http")
    async def authenticate(request, call_next):
        supplied = request.headers.get("authorization", "")
        expected = "Bearer " + config["connection_key"]
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    def invoke(operation, arguments):
        # Workspace hydration probes both apps concurrently on this one workstation.
        acquired = lock.acquire(timeout=10) if operation == "status" else lock.acquire(blocking=False)
        if not acquired:
            raise HTTPException(503, "The workstation is busy")
        try:
            value = execute(config, operation, arguments)
            return {"protocol": PROTOCOL, "instance_id": config["instance_id"], **(
                value if operation == "status" else {"result": value})}
        except TimeoutError:
            raise HTTPException(503, "The desktop application did not respond") from None
        except (ValueError, OSError, KeyError):
            raise HTTPException(422, "Check the connector console, current job, approved rate book and requested parameters") from None
        finally:
            lock.release()

    @app.get("/v1/status")
    def status():
        return invoke("status", {})

    @app.post("/v1/invoke")
    async def execute_operation(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16000:
                raise HTTPException(413, "Request too large")
        try:
            payload = json.loads(body)
            if set(payload) != {"operation", "arguments"} or payload["operation"] not in DEFINITIONS:
                raise ValueError()
            arguments = DEFINITIONS[payload["operation"]][1].model_validate(payload["arguments"]).model_dump(mode="json")
        except (ValueError, TypeError, KeyError):
            raise HTTPException(422, "Invalid operation or parameters") from None
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(invoke, payload["operation"], arguments)

    @app.get("/v1/reports/{report_id}")
    def download(report_id: str):
        try:
            receipt = get_estimate(store, report_id)
            path = store.path("Reports", report_id, ".xlsx")
            if path.stat().st_size > 12_000_000:
                raise ValueError()
        except (ValueError, OSError, KeyError):
            raise HTTPException(404, "Verified report not found") from None
        return FileResponse(path, filename=receipt["filename"], media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("This connector requires Windows with licensed PlanSwift and Microsoft Excel")
    config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    # One server process per data folder, even if a second launcher uses another port.
    import msvcrt
    store = Store(config["data_folder"])
    with (store.root / "connector.lock").open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        import uvicorn
        uvicorn.run(create_app(config), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
