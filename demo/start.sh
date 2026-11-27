#!/usr/bin/env bash
# Démarre la démo HOVIS : serveur du scénario (port 8000) et interface argos-ui (port 5173).
#
#   ./demo/start.sh               # avec l'analyse sécurité EPI (webcam), si ses poids sont là
#   SAFETY=0 ./demo/start.sh      # sans l'analyse webcam
#
# Les deux serveurs tournent dans ce terminal ; Ctrl+C arrête les deux.
# Si le port 8000 ou 5173 est déjà pris, le processus qui l'occupe est arrêté d'abord.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "$REPO/.venv/Scripts/python.exe" ]; then PYTHON="$REPO/.venv/Scripts/python.exe"  # Windows (Git Bash)
elif [ -x "$REPO/.venv/bin/python" ]; then PYTHON="$REPO/.venv/bin/python"                # Linux / macOS
else PYTHON="python"; fi

# Ports déjà pris : on arrête le processus qui les occupe, puis on les réutilise.
free_port() {
  local port=$1
  if command -v powershell >/dev/null 2>&1; then   # Windows (Git Bash)
    powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Write-Host \"Port $port occupe par PID \$_ : arret.\"; Stop-Process -Id \$_ -Force }"
  elif command -v fuser >/dev/null 2>&1; then      # Linux
    fuser -k "$port/tcp" 2>/dev/null && echo "Port $port libéré." || true
  elif command -v lsof >/dev/null 2>&1; then       # macOS
    lsof -ti "tcp:$port" | xargs -r kill -9 && echo "Port $port libéré." || true
  fi
}
free_port 8000
free_port 5173
sleep 1

cd "$REPO"
SAFETY="${SAFETY:-1}" "$PYTHON" -m uvicorn demo.scenario:app --port 8000 --host 127.0.0.1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT

cd "$REPO/argos-ui"
[ -d node_modules ] || npm install --no-audit --no-fund
echo "Interface : http://localhost:5173 (le serveur du scénario met environ 20 s à charger les modèles)"
echo "Clic sur le logo HOVIS = lancer / relancer la simulation ; Ctrl+M = vue superviseur ; Ctrl+P = poste suivant."
VITE_USE_MOCK=false npx vite --port 5173 --host 127.0.0.1
