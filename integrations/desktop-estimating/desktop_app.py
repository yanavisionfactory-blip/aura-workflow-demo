"""User-session Windows companion. Bundled runtime, explicit pairing, no open port."""
import argparse
import json
import multiprocessing
import os
import queue
import secrets
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from desktop_client import ClientError, DesktopClient, pairing_code
from setup_rates import create_template


def private_folder(folder):
    import win32api
    import win32con
    import win32security
    folder.mkdir(parents=True, exist_ok=True)
    user = win32security.GetTokenInformation(
        win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY),
        win32security.TokenUser)[0]
    system = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    acl = win32security.ACL()
    for sid in (user, system):
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION,
            win32con.OBJECT_INHERIT_ACE | win32con.CONTAINER_INHERIT_ACE, 0x1F01FF, sid)
    win32security.SetNamedSecurityInfo(str(folder), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, acl, None)


def load_config(folder):
    private_folder(folder)
    path = folder / "config.json"
    config = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    config.setdefault("instance_id", str(uuid4()))
    config.setdefault("device_token", secrets.token_urlsafe(48))
    config.setdefault("data_folder", str(folder / "Data"))
    if "planswift_progid" not in config:
        import winreg
        config["planswift_progid"] = "PlanSwift9.PlanSwift"
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "PlanSwift.PlanSwift12"):
                config["planswift_progid"] = "PlanSwift.PlanSwift12"
        except OSError:
            pass
    client = DesktopClient(config, path)
    client.save()
    create_template(config["data_folder"])
    return client


def install_helper(folder):
    """Called only after the user selects Install; HKCU registration needs no admin."""
    import winreg
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Use the packaged AURA-Desktop.exe to install the helper")
    destination = folder / "AURA-Desktop.exe"
    if Path(sys.executable).resolve() != destination.resolve():
        shutil.copy2(sys.executable, destination)
    key = r"Software\Classes\aura-estimator"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
        winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, "URL:AURA Desktop")
        winreg.SetValueEx(handle, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\shell\open\command") as handle:
        winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, f'"{destination}" --pair "%1"')


def instance_lock(folder, activation):
    import msvcrt
    handle = (folder / "desktop.lock").open("a+b")
    handle.seek(0)
    if not handle.read(1):
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        if activation:
            temporary = folder / ("activation-" + uuid4().hex + ".tmp")
            temporary.write_text(pairing_code(activation), encoding="utf-8")
            temporary.replace(folder / "activation.txt")
        return None
    return handle


def serve(client, stop, events):
    """Keep heartbeats alive during COM work; retry receipts without repeating work."""
    pending, future, receipt = None, None, None
    with ThreadPoolExecutor(max_workers=1) as pool:
        while not stop.is_set():
            try:
                if future is not None and future.done():
                    try:
                        receipt = future.result()
                    except Exception as exc:  # noqa: BLE001 -- isolate local application failures
                        events.put(("status", "Operation stopped: " + str(exc)[:220]))
                        receipt = {"ok": False}
                    future = None
                if receipt is not None:
                    try:
                        client.send_result(pending["id"], receipt)
                    except ClientError as exc:
                        if exc.status != 410:
                            raise
                        events.put(("status", "AURA timed out. The saved result was kept; no action was repeated."))
                    pending, receipt = None, None
                command = client.poll(busy=pending is not None)
                if command is not None and pending is None:
                    pending = command
                    events.put(("status", "Working: " + str(command.get("operation", "application task"))))
                    future = pool.submit(client.perform, command)
                elif pending is None:
                    events.put(("status", "Connected to " + client.config.get("workspace_name", "AURA") + ". Ready for a workflow."))
            except ClientError as exc:
                events.put(("status", str(exc)))
                if exc.status in {401, 403}:
                    events.put(("revoked", "Access was revoked. Pair again in AURA."))
                    return
            except Exception as exc:  # noqa: BLE001 -- keep the connection UI responsive
                events.put(("status", "Connection paused: " + str(exc)[:220]))
            stop.wait(2)


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        # Packaging check: imports include Windows COM, workbook libraries and GUI.
        import tkinter

        import win32com.client
        assert tkinter.TkVersion >= 8
        assert win32com.client.Dispatch
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix="aura-desktop-check-") as directory:
            client = load_config(Path(directory) / "helper")
            assert (Path(client.config["data_folder"]) / "Rates" / "Approved-Rates.xlsx").exists()
            # Exercise frozen multiprocessing without requiring licensed applications.
            assert client.execute(client.config, "excel.ratebooks.list", {}) == {"rate_books": ["Approved-Rates.xlsx"]}
            try:
                client.execute(client.config, "unsupported-self-test-operation", {})
            except ValueError:
                pass
            else:
                raise AssertionError("A failed child operation did not return its error receipt")
        return
    if os.name != "nt":
        raise SystemExit("AURA Desktop requires Windows")
    import tkinter as tk
    from tkinter import messagebox, ttk

    folder = Path(os.environ["LOCALAPPDATA"]) / "AURA" / "EstimatingConnector"
    private_folder(folder)
    activation = pairing_code(args.pair) if args.pair else None
    handle = instance_lock(folder, activation)
    if handle is None:
        return
    client = load_config(folder)
    events, stop = queue.Queue(), threading.Event()
    root = tk.Tk()
    root.title("AURA Desktop")
    root.geometry("590x440")
    panel = ttk.Frame(root, padding=24)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="Connect your computer", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(panel, text="AURA reads existing quantities and approved rates, and creates\nnew Excel estimates. Keep this helper open while workflows run.", wraplength=530).pack(anchor="w", pady=12)
    status = tk.StringVar(value="Install the helper once, then click Connect in AURA.")
    ttk.Label(panel, textvariable=status, wraplength=530).pack(anchor="w", pady=10)
    code = tk.StringVar(value=activation or "")
    ttk.Label(panel, text="Pairing code (only if AURA did not open this helper)").pack(anchor="w")
    entry = ttk.Entry(panel, textvariable=code, width=70)
    entry.pack(fill="x", pady=6)
    version = tk.StringVar(value="12" if client.config["planswift_progid"] == "PlanSwift.PlanSwift12" else "11")
    row = ttk.Frame(panel)
    row.pack(fill="x", pady=6)
    ttk.Label(row, text="PlanSwift version").pack(side="left")
    ttk.Combobox(row, textvariable=version, values=["11", "12"], state="readonly", width=5).pack(side="left", padx=8)
    working = [False]
    worker = [None]

    def start_service():
        if worker[0] and worker[0].is_alive():
            return
        stop.clear()
        worker[0] = threading.Thread(target=serve, args=(client, stop, events), daemon=True)
        worker[0].start()

    def pair():
        if working[0]:
            return
        try:
            candidate = pairing_code(code.get())
        except (ValueError, TypeError) as exc:
            status.set(str(exc))
            return
        working[0] = True
        connect_button.configure(state="disabled")
        status.set("Checking the pairing request…")

        def inspect():
            try:
                info = client.info(candidate)
                events.put(("confirm", (candidate, info["workspace_name"])))
            except Exception as exc:  # noqa: BLE001 -- report bounded pairing diagnostics
                events.put(("error", str(exc)[:300]))
        threading.Thread(target=inspect, daemon=True).start()

    def install():
        try:
            install_helper(folder)
            status.set("Helper installed. Return to AURA and use the app's Connect button.")
        except (OSError, RuntimeError) as exc:
            status.set("Installation could not finish: " + str(exc)[:200])

    buttons = ttk.Frame(panel)
    buttons.pack(fill="x", pady=12)
    ttk.Button(buttons, text="Install helper", command=install).pack(side="left")
    connect_button = ttk.Button(buttons, text="Authorize connection", command=pair)
    connect_button.pack(side="left", padx=10)
    ttk.Label(panel, text="Closing this window stops the connection. Existing source files stay unchanged.", wraplength=530).pack(anchor="w", pady=8)

    def process_events():
        pending_path = folder / "activation.txt"
        if pending_path.exists() and not working[0]:
            try:
                code.set(pairing_code(pending_path.read_text(encoding="utf-8")))
                pending_path.unlink()
                root.deiconify()
                root.lift()
                pair()
            except (ValueError, OSError):
                status.set("The pairing link was invalid. Copy a fresh code from AURA.")
                pending_path.unlink(missing_ok=True)
        while True:
            try:
                kind, value = events.get_nowait()
            except queue.Empty:
                break
            if kind == "confirm":
                candidate, workspace = value
                approved = client.config.get("workspace_id") == candidate.split(".")[0] or messagebox.askyesno("Allow this AURA workspace?",
                    f'Allow “{workspace}” to read PlanSwift takeoffs and approved rate books, and create and download new Excel estimates?\n\nAURA cannot measure drawings or edit your source workbooks through this helper.')
                if not approved:
                    working[0] = False
                    connect_button.configure(state="normal")
                    status.set("Pairing cancelled on this computer.")
                    continue
                client.config["planswift_progid"] = "PlanSwift.PlanSwift12" if version.get() == "12" else "PlanSwift9.PlanSwift"
                client.save()
                status.set("Checking PlanSwift and Excel. This can take up to 90 seconds…")
                def finish_pair(pair_code=candidate):
                    try:
                        events.put(("paired", client.pair(pair_code)))
                    except Exception as exc:  # noqa: BLE001 -- GUI worker boundary
                        events.put(("error", str(exc)[:300]))
                threading.Thread(target=finish_pair, daemon=True).start()
            elif kind == "paired":
                code.set("")
                working[0] = False
                connect_button.configure(state="normal")
                start_service()
            elif kind in {"error", "revoked"}:
                working[0] = False
                connect_button.configure(state="normal")
                status.set(value)
            else:
                status.set(value)
        root.after(400, process_events)

    def close():
        stop.set()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    if client.config.get("workspace_id"):
        start_service()
    if activation:
        root.after(100, pair)
    root.after(400, process_events)
    root.mainloop()
    handle.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        if "--self-test" in sys.argv:
            import traceback
            Path("desktop-selftest-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            raise SystemExit(1) from None
        raise
