$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "Creating virtual environment..."
  python -m venv .venv
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create virtual environment. Ensure Python 3.10+ is installed and on PATH."
    exit 1
  }
}

. ".venv\Scripts\Activate.ps1"

Write-Host "Ensuring dependencies are installed..."
python -m pip install --upgrade pip | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Failed to upgrade pip."
  exit 1
}

python -m pip install -e .
if ($LASTEXITCODE -ne 0) {
  Write-Host "Failed to install dependencies."
  exit 1
}

Write-Host "Starting Semiapply at http://127.0.0.1:8000/"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
