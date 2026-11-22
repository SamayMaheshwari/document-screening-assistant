# Starts the whole app (API + built UI) on http://127.0.0.1:8000
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$root\backend"
if (-not (Test-Path "$root\frontend\dist")) { Write-Host "Frontend not built. Run .\setup.ps1 first." -ForegroundColor Yellow; exit 1 }
Write-Host "Open http://127.0.0.1:8000  (logins: officer/officer, admin/admin, auditor/auditor)" -ForegroundColor Cyan
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
