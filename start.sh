#!/usr/bin/env bash
# One command: install if needed, build the web app, and serve everything on http://127.0.0.1:8000
# (another port: PORT=8001 ./start.sh)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x backend/.venv/bin/python ]; then
  echo "Setting up Python environment (first run only)..."
  python3 -m venv backend/.venv
  backend/.venv/bin/python -m pip install -q --upgrade pip
  backend/.venv/bin/python -m pip install -q -r backend/requirements.txt
fi
if [ ! -d frontend/node_modules ]; then
  echo "Installing web app packages (first run only)..."
  (cd frontend && npm install --silent)
fi
echo "Building the web app..."
(cd frontend && npm run build --silent)

echo ""
PORT="${PORT:-8000}"
echo "UmmaCare is starting: open http://127.0.0.1:${PORT}   (Ctrl-C to stop)"
# No --reload: one process, so an edit never spawns duplicate servers.
exec backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --app-dir backend
