# One-time setup. Everything installs inside this folder (no admin rights, nothing system-wide).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$root\backend"
if (-not (Test-Path ".venv")) { python -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
Set-Location "$root\frontend"
npm install --no-audit --no-fund
npm run build
Set-Location "$root\backend"
.\.venv\Scripts\python -m scripts.calibrate_forensics 80
.\.venv\Scripts\python -m scripts.seed_demo --reset --all
Write-Host "`nSetup complete. Start the demo with:  .\run_demo.ps1" -ForegroundColor Green
