#!/usr/bin/env bash
# build-backend.sh — compile FastAPI backend with PyInstaller (macOS/Linux)
# and stage it into desktop/resources/backend
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$ROOT/backend"
DEST="$ROOT/desktop/resources/backend"

echo "[1/4] Ensuring venv + deps..."
if [ ! -x "$ROOT/venv/bin/python" ]; then python3 -m venv "$ROOT/venv"; fi
source "$ROOT/venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$ROOT/requirements.txt" pyinstaller -q

echo "[2/4] Running PyInstaller (this takes a while)..."
cd "$BACKEND"
pyinstaller bizassist-backend.spec --noconfirm

echo "[3/4] Staging into desktop/resources/backend..."
rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -R "$BACKEND/dist/bizassist-backend" "$DEST"

echo "[4/4] Smoke test (health check)..."
"$DEST/bizassist-backend" --port 8009 & PID=$!
for i in $(seq 1 30); do
  sleep 1
  if curl -sf http://127.0.0.1:8009/health >/dev/null; then echo "OK"; break; fi
  if [ "$i" = 30 ]; then echo "WARNING: health check failed — inspect manually"; fi
done
kill "$PID" 2>/dev/null || true

echo "Done. Backend staged at $DEST"
