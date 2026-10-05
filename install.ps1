$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "=== BEVIMS installer ==="
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { Write-Host "[ERROR] Python 3.10+ not found. Install from https://www.python.org/downloads/"; exit 1 }
python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)"
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Python 3.10 or newer is required."; exit 1 }
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env from .env.example" }
New-Item -ItemType Directory -Force data | Out-Null
& .\.venv\Scripts\python.exe -m app.database.init_db
Write-Host "`n===== INSTALLATION COMPLETE =====`n  1. Run run.bat`n  2. Open http://127.0.0.1:8000"
