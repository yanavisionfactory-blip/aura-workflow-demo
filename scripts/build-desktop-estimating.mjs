import fs from "node:fs";
import path from "node:path";
import { zipSync } from "fflate";

const root = process.cwd();
const source = path.join(root, "integrations/desktop-estimating");
const files = {};
for (const name of ["aura_estimator.py", "windows_apps.py", "estimate_core.py", "install.ps1", "requirements.txt", "setup_rates.py", "README.md"]) {
  files[name] = [new Uint8Array(fs.readFileSync(path.join(source, name))), { mtime: new Date("2026-01-01T00:00:00Z") }];
}
files["estimating_contract.py"] = [new Uint8Array(fs.readFileSync(path.join(root, "backend/app/estimating_contract.py"))), { mtime: new Date("2026-01-01T00:00:00Z") }];
const destination = path.join(root, "public/downloads/aura-desktop-estimating.zip");
fs.mkdirSync(path.dirname(destination), { recursive: true });
fs.writeFileSync(destination, zipSync(files));
