param(
    [ValidateSet("11", "12")][string]$PlanSwiftVersion = "11",
    [string]$InstallFolder = "$env:LOCALAPPDATA\AURA\EstimatingConnector"
)
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Windows is required." }
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Install Python 3.12 for Windows from python.org, then run this installer again." }
New-Item -ItemType Directory -Force -Path $InstallFolder | Out-Null
$DataFolder = Join-Path $InstallFolder "Data"
New-Item -ItemType Directory -Force -Path $DataFolder | Out-Null
$CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $InstallFolder /inheritance:r /grant:r "${CurrentIdentity}:(OI)(CI)F" "SYSTEM:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not restrict connector files to this Windows account." }
foreach ($File in @("aura_estimator.py", "desktop_app.py", "desktop_client.py", "windows_apps.py", "estimate_core.py", "estimating_contract.py", "requirements.txt", "setup_rates.py", "README.md")) {
    Copy-Item (Join-Path $PSScriptRoot $File) (Join-Path $InstallFolder $File) -Force
}
& py -3.12 -m venv (Join-Path $InstallFolder ".venv")
if ($LASTEXITCODE -ne 0) { throw "Python 3.12 is required; PlanSwift 12 needs 64-bit Python." }
$PythonExe = Join-Path $InstallFolder ".venv\Scripts\python.exe"
& $PythonExe -m pip install -r (Join-Path $InstallFolder "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Connector dependencies could not be installed." }
$ConfigFile = Join-Path $InstallFolder "config.json"
if (-not (Test-Path $ConfigFile)) {
    $RandomBytes = New-Object byte[] 48
    $Generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $Generator.GetBytes($RandomBytes)
    $Generator.Dispose()
    $Config = @{
        instance_id = [guid]::NewGuid().ToString()
        connection_key = [Convert]::ToBase64String($RandomBytes)
        data_folder = $DataFolder
        planswift_progid = $(if ($PlanSwiftVersion -eq "12") { "PlanSwift.PlanSwift12" } else { "PlanSwift9.PlanSwift" })
    }
    $Config | ConvertTo-Json | Set-Content -Encoding UTF8 $ConfigFile
}
& $PythonExe (Join-Path $InstallFolder "setup_rates.py") --folder $DataFolder
if ($LASTEXITCODE -ne 0) { throw "Could not create the empty rate template." }
# No service, startup task, firewall rule or public endpoint is created automatically.
$Launcher = '@echo off' + "`r`n" + '"%~dp0.venv\Scripts\python.exe" "%~dp0aura_estimator.py" --config "%~dp0config.json"' + "`r`npause`r`n"
$Launcher | Set-Content -Encoding ASCII (Join-Path $InstallFolder "Start Connector.cmd")
Write-Host "Installed in $InstallFolder"
Write-Host "1. Fill Data\Rates\Approved-Rates.xlsx with approved rates."
Write-Host "2. Open PlanSwift and Excel; run Start Connector.cmd."
Write-Host "3. Follow README.md to expose the loopback connector using your approved HTTPS tunnel."
Write-Host "4. In AURA connect PlanSwift and Microsoft Excel (Desktop) with that HTTPS address and the connection_key in config.json."
