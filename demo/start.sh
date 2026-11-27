#!/usr/bin/env bash
# Démarre la démo HOVIS : serveur du scénario (port 8000) et interface argos-ui (port 5173).
#
#   ./demo/start.sh               # avec l'analyse sécurité EPI (webcam), si ses poids sont là
#   SAFETY=0 ./demo/start.sh      # sans l'analyse webcam
#
# Les deux serveurs tournent dans ce terminal ; Ctrl+C arrête les deux.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "$REPO/.venv/Scripts/python.exe" ]; then PYTHON="$REPO/.venv/Scripts/python.exe"  # Windows (Git Bash)
elif [ -x "$REPO/.venv/bin/python" ]; then PYTHON="$REPO/.venv/bin/python"                # Linux / macOS
else PYTHON="python"; fi

cd "$REPO"
SAFETY="${SAFETY:-1}" "$PYTHON" -m uvicorn demo.scenario:app --port 8000 --host 127.0.0.1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT

cd "$REPO/argos-ui"
[ -d node_modules ] || npm install --no-audit --no-fund
echo "Interface : http://localhost:5173 (le serveur du scénario met environ 20 s à charger les modèles)"
echo "Clic sur le logo HOVIS = lancer / relancer la simulation ; Ctrl+M = vue superviseur."
VITE_USE_MOCK=false npx vite --port 5173 --host 127.0.0.1
