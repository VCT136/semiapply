@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create virtual environment. Ensure Python 3.10+ is installed and on PATH.
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"

echo Ensuring dependencies are installed...
python -m pip install --upgrade pip >nul
python -m pip install -e .
if errorlevel 1 (
  echo Failed to install dependencies.
  exit /b 1
)

echo Starting Semiapply at http://127.0.0.1:8000/
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
