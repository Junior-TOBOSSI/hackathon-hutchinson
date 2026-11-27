#!/usr/bin/env bash
# Démarre la démo HOVIS : un serveur PAR POSTE actif (ports 8001...), le serveur de la
# cellule C3 (port 8000) et l'interface argos-ui (port 5173).
#
#   ./demo/start.sh               # 1 poste actif (C3·P06), les 5 autres sans activité
#   ./demo/start.sh 3             # 3 postes actifs : C3·P06, C3·P01, C3·P02
#   SAFETY=0 ./demo/start.sh 3    # sans l'analyse webcam EPI (faite par C3·P06)
#
# Tous les serveurs tournent dans ce terminal (logs mêlés, préfixés par le poste) ;
# Ctrl+C arrête tout. Si un port (8000 à 8006, 5173) est pris, son processus est arrêté.
set -euo pipefail

STATIONS="${1:-1}"
if ! [[ "$STATIONS" =~ ^[1-6]$ ]]; then echo "Nombre de postes : 1 à 6" >&2; exit 1; fi
ORDER=("C3·P06" "C3·P01" "C3·P02" "C3·P03" "C3·P04" "C3·P05")

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
for port in 8000 8001 8002 8003 8004 8005 8006 5173; do free_port "$port"; done
sleep 1

cd "$REPO"
PIDS=()
trap 'kill "${PIDS[@]}" 2>/dev/null' EXIT
for ((k = 0; k < STATIONS; k++)); do
  safety=0
  if [ "$k" -eq 0 ]; then safety="${SAFETY:-1}"; fi   # la webcam = C3·P06
  STATION_ID="${ORDER[$k]}" PROFILE="$k" PORT="$((8001 + k))" SAFETY="$safety" \
    "$PYTHON" -m uvicorn demo.station_server:app --port "$((8001 + k))" --host 127.0.0.1 &
  PIDS+=($!)
done
ACTIVE_STATIONS="$STATIONS" "$PYTHON" -m uvicorn demo.cell_server:app --port 8000 --host 127.0.0.1 &
PIDS+=($!)

cd "$REPO/argos-ui"
[ -d node_modules ] || npm install --no-audit --no-fund
echo "Postes actifs : ${ORDER[*]:0:$STATIONS} ; les autres : pas d'activité."
echo "Interface : http://localhost:5173 (les serveurs des postes mettent environ 20 s à charger les modèles)"
echo "Clic sur le logo HOVIS = lancer / relancer le poste affiché (chaque poste se lance à la main) ; Ctrl+M = vue superviseur ; Ctrl+P = poste suivant."
VITE_USE_MOCK=false npx vite --port 5173 --host 127.0.0.1
