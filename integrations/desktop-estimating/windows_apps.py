"""Read-only PlanSwift COM access and an isolated Excel recalculation process.

PlanSwift calls follow the vendor's VB.Net Microsoft Office SDK example:
https://github.com/PlanSwift/sdk-examples-2010/blob/master/VB.Net/Microsoft%20Office/PSSDK9/Form1.vb
"""
import time

from estimate_core import MAX_ROWS, digest, number, text


class WindowsApps:
    def __init__(self, config, dispatch=None, dispatch_ex=None):
        if dispatch is None:
            import win32com.client
            dispatch, dispatch_ex = win32com.client.Dispatch, win32com.client.DispatchEx
        self.dispatch, self.dispatch_ex = dispatch, dispatch_ex
        self.progid = config.get("planswift_progid", "PlanSwift9.PlanSwift")
        if self.progid not in {"PlanSwift9.PlanSwift", "PlanSwift.PlanSwift12"}:
            raise ValueError("Select the documented PlanSwift 11 or 12 COM program")

    def status(self):
        applications = {}
        try:
            ps = self.dispatch(self.progid)
            version = str(ps.CurrentVersion)
            if not bool(ps.IsLoaded):
                raise ValueError("PlanSwift is not loaded")
            applications["planswift"] = {"available": True, "version": version}
        except Exception:  # noqa: BLE001 -- COM activation errors must yield an unavailable application probe
            applications["planswift"] = {"available": False, "version": ""}
        excel = None
        try:
            excel = self.dispatch_ex("Excel.Application")
            applications["excel-desktop"] = {"available": True, "version": str(excel.Version)}
        except Exception:  # noqa: BLE001 -- COM activation errors must yield an unavailable application probe
            applications["excel-desktop"] = {"available": False, "version": ""}
        finally:
            if excel is not None:
                excel.Quit()
        return applications

    def takeoff(self, request):
        ps = self.dispatch(self.progid)
        if not bool(ps.IsJobOpen):
            raise ValueError("Open the intended PlanSwift job first")
        job = ps.GetItem(ps.Root.FullPath + "\\Job")
        if str(job.Name).strip() != request["job_name"]:
            raise ValueError("The active PlanSwift job does not match the requested job name")
        job_id, version = str(job.GUID), str(ps.CurrentVersion)

        def scan():
            root = ps.GetItem(ps.Root.FullPath + "\\Job\\Takeoff")
            if root is None:
                raise ValueError("The active job has no Takeoff folder")
            rows, seen = [], set()
            stack = [root]
            visited = 0
            while stack:
                parent = stack.pop()
                visited += 1
                if visited > 20000:
                    raise ValueError("PlanSwift job exceeds the supported traversal limit")
                # The vendor's IItem API is zero-indexed; do not include both assemblies and parts in pricing.
                children = [parent.ChildItem(index) for index in range(int(parent.ChildCount))]
                for item in children:
                    identifier = str(item.GUID)
                    if identifier in seen:
                        raise ValueError("PlanSwift returned a repeated item; no partial snapshot was saved")
                    seen.add(identifier)
                    kind = str(item.GetProperty("type").ResultAsString)
                    if kind == "Folder":
                        stack.append(item)
                        continue
                    is_part = bool(item.GetPropertyResultAsBoolean("IsPart", False))
                    is_measurement = any(bool(item.GetPropertyResultAsBoolean(flag, False))
                                         for flag in ("IsArea", "IsLinear", "IsSegment", "IsCount"))
                    include = bool(item.GetPropertyResultAsBoolean("IsItem", False)) and (
                        is_part if request["quantity_scope"] == "parts" else is_measurement)
                    if include:
                        prop = item.GetProperty("Qty")
                        rows.append({
                            "item_id": text(identifier, "Item GUID"),
                            "cost_code": text(str(item.GetPropertyResultAsString("Item #", "")), "Item #"),
                            "description": text(str(item.Name), "Item name"),
                            "unit": text(str(prop.Units), "Quantity unit").upper(),
                            "quantity": str(number(prop.ResultAsFloat, "PlanSwift Qty")),
                            "source_path": str(item.FullPath),
                        })
                        if len(rows) > MAX_ROWS:
                            raise ValueError("Takeoff exceeds 5000 rows; partial estimates are not allowed")
                    if int(item.ChildCount) > 0:
                        stack.append(item)
            return sorted(rows, key=lambda item: item["item_id"])

        first = scan()
        second = scan()
        current_job = ps.GetItem(ps.Root.FullPath + "\\Job")
        if str(current_job.GUID) != job_id or digest(first) != digest(second):
            raise ValueError("The PlanSwift job changed during capture; stop editing and retry")
        return {"job_id": job_id, "job_name": request["job_name"], "revision": request["revision"],
                "revision_source": "user_supplied", "quantity_scope": request["quantity_scope"],
                "application": "PlanSwift", "version": version,
                "coverage": "Existing takeoff items only; drawing scale and completeness require user review"}, first

    def recalculate(self, path):
        excel, workbook = None, None
        try:
            excel = self.dispatch_ex("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            excel.EnableEvents = False
            excel.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
            workbook = excel.Workbooks.Open(str(path.resolve()), UpdateLinks=0, ReadOnly=False,
                                            IgnoreReadOnlyRecommended=True, AddToMru=False)
            if workbook.ReadOnly:
                raise ValueError("The output workbook is locked")
            excel.CalculateFullRebuild()
            deadline = time.monotonic() + 60
            while excel.CalculationState != 0:
                if time.monotonic() > deadline:
                    raise TimeoutError("Excel calculation timed out")
                time.sleep(0.1)
            workbook.Save()
        finally:
            try:
                if workbook is not None:
                    workbook.Close(SaveChanges=False)
            finally:
                if excel is not None:
                    excel.Quit()
