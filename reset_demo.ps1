# Wipes the demo database and re-seeds the demo cases (stored files are left in data/storage).
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$root\backend"
.\.venv\Scripts\python -m scripts.seed_demo --reset --all
