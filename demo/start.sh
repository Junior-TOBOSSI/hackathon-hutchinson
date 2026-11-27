#!/usr/bin/env bash
# Démarre la démo HOVIS : un serveur PAR POSTE actif (ports 8001...), le serveur de la
# cellule C3 (port 8000) et l'interface argos-ui (port 5173).
#
#   ./demo/start.sh               # 1 poste actif (C3·P06), les 5 autres sans activité
#   ./demo/start.sh 3             # 3 postes actifs : C3·P06, C3·P01, C3·P02
#   SAFETY=0 ./demo/start.sh 3    # sans l'analyse webcam EPI (faite par C3·P06)
#   ./demo/start.sh 3 auto        # mode NOK auto : la ligne continue (défaut : manuel)
#   ./demo/start.sh 2 manuel press_cell:nok,electrical_bench   # poste de travail de chaque poste
#   VIDEO_SPEED=0.5 ./demo/start.sh 2 auto   # vitesse de lecture des vidéos (VIDEO=... par poste)
#
# Tous les serveurs tournent dans ce terminal (logs mêlés, préfixés par le poste) ;
# Ctrl+C arrête tout. Si un port (8000 à 8006, 5173) est pris, son processus est arrêté.
set -euo pipefail

STATIONS="${1:-1}"
MODE="${2:-manuel}"
IFS=',' read -r -a WORKSTATIONS <<< "${3:-}"   # un poste de travail par poste actif (optionnel)
case "$MODE" in auto) QUALITY_MODE=auto ;; manuel|manual) QUALITY_MODE=manual ;; *) echo "Mode : manuel ou auto" >&2; exit 1 ;; esac
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
for port in 8000 8001 8002 8003 8004 8005 8006 8040 5173; do free_port "$port"; done
sleep 1

cd "$REPO"
PIDS=()
trap 'kill "${PIDS[@]}" 2>/dev/null' EXIT
for ((k = 0; k < STATIONS; k++)); do
  safety=0
  if [ "$k" -eq 0 ]; then safety="${SAFETY:-1}"; fi   # la webcam = C3·P06
  STATION_ID="${ORDER[$k]}" PROFILE="$k" PORT="$((8001 + k))" SAFETY="$safety" QUALITY_MODE="$QUALITY_MODE" WORKSTATION="${WORKSTATIONS[$k]:-}" VIDEO_SPEED="${VIDEO_SPEED:-1}" \
    "$PYTHON" -m uvicorn demo.station_server:app --port "$((8001 + k))" --host 127.0.0.1 &
  PIDS+=($!)
done
ACTIVE_STATIONS="$STATIONS" "$PYTHON" -m uvicorn demo.cell_server:app --port 8000 --host 127.0.0.1 &
PIDS+=($!)
# Espace AI leader (mlops/, port 8040, Ctrl+O) : son propre venv .venv-mlops, lit Databricks
# (databricks auth login --profile ARGOS). NO_AI_LEADER=1 : ne pas le démarrer.
if [ -x "$REPO/.venv-mlops/Scripts/python.exe" ]; then MLOPS_PY="$REPO/.venv-mlops/Scripts/python.exe"
elif [ -x "$REPO/.venv-mlops/bin/python" ]; then MLOPS_PY="$REPO/.venv-mlops/bin/python"; else MLOPS_PY=""; fi
if [ "${NO_AI_LEADER:-0}" != "1" ]; then
  if [ -n "$MLOPS_PY" ]; then
    ( [ -f hovis.local.env ] && set -a && . ./hovis.local.env && set +a; MLFLOW_DISABLE_AGENT_HINT=1       exec "$MLOPS_PY" -m uvicorn mlops.api.app:app --port 8040 --host 127.0.0.1 ) &
    PIDS+=($!)
  else
    echo "Espace AI leader non démarré : .venv-mlops absent (voir demo/README.md)." >&2
  fi
fi

cd "$REPO/argos-ui"
[ -d node_modules ] || npm install --no-audit --no-fund
echo "Postes actifs : ${ORDER[*]:0:$STATIONS} ; les autres : pas d'activité."
echo "Interface : http://localhost:5173 (les serveurs des postes mettent environ 20 s à charger les modèles)"
echo "Clic sur le logo HOVIS = lancer / relancer le poste affiché (chaque poste se lance à la main) ; Ctrl+M = vue superviseur ; Ctrl+P = poste suivant ; Ctrl+O = espace AI leader."
VITE_USE_MOCK=false npx vite --port 5173 --host 127.0.0.1
