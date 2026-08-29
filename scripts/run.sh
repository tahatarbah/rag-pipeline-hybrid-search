#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
echo "Open http://127.0.0.1:8765  (first visit is the setup wizard)"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
