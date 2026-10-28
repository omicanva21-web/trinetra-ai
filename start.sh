#!/usr/bin/env bash
# Trinetra AI launcher for macOS / Linux
set -e
cd "$(dirname "$0")"
PY=$(command -v python3.11 || command -v python3 || command -v python || true)
[ -z "$PY" ] && { echo "Python 3.9+ not found. Install it from https://www.python.org/downloads/"; exit 1; }
"$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" || { echo "Python 3.9+ needed."; exit 1; }
if [ ! -x backend/.venv/bin/python ]; then
  echo "[1/4] Creating the Python environment in backend/.venv ..."
  "$PY" -m venv backend/.venv
fi
VPY="$(pwd)/backend/.venv/bin/python"
if [ ! -f backend/.venv/core-installed-v2.txt ]; then
  echo "[2/4] Installing packages (first run only, about 2-5 minutes) ..."
  "$VPY" -m pip install --upgrade pip
  "$VPY" -m pip install -r backend/requirements-core.txt
  echo ok > backend/.venv/core-installed-v2.txt
fi
if [ ! -f backend/.venv/speedup-v3.txt ]; then
  echo "      Optional speed-up for Dense crowd mode: ONNX Runtime ..."
  "$VPY" -m pip install "onnxruntime>=1.17" && echo ok > backend/.venv/speedup-v3.txt \
    || echo "      Not installed - Dense crowd mode still works, about 2x slower."
fi
[ -f .env ] || cp .env.example .env
echo "[3/4] Checking the sample video ..."
"$VPY" backend/tools/get_sample_video.py
echo "[4/4] Starting Trinetra. The dashboard opens in your browser. Ctrl+C to stop."
exec "$VPY" backend/run.py "$@"
