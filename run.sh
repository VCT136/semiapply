#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment..."
  if ! python3 -m venv .venv; then
    echo "Failed to create virtual environment. Ensure Python 3.10+ is installed and on PATH."
    exit 1
  fi
fi

# shellcheck source=/dev/null
source ".venv/bin/activate"

echo "Ensuring dependencies are installed..."
python -m pip install --upgrade pip >/dev/null
if ! python -m pip install -e .; then
  echo "Failed to install dependencies."
  exit 1
fi

echo "Starting Semiapply at http://127.0.0.1:8000/"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
