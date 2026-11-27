<#
Démarre la démo HOVIS : un serveur PAR POSTE actif (ports 8001, 8002, ...), le serveur de
la cellule C3 (port 8000, celui que l'interface appelle) et l'interface argos-ui (5173),
chacun dans sa fenêtre, puis ouvre le navigateur.

    .\demo\start.ps1                # 1 poste actif (C3·P06), les 5 autres sans activité
    .\demo\start.ps1 -Stations 3    # 3 postes actifs : C3·P06, C3·P01, C3·P02
    .\demo\start.ps1 -Stations 6 -NoSafety   # sans l'analyse webcam EPI
    .\demo\start.ps1 -Stations 3 -Mode auto  # NOK sans arrêt de la ligne (défaut : -Mode manuel)

Postes activés dans cet ordre : C3·P06, P01, P02, P03, P04, P05.
- P06 et P01 : Machine cell variant, vérification du poste KO, KO, puis OK ;
- P02 : Press cell (un AUTRE poste de travail), poste OK d'emblée ; P03 : Electrical bench,
  P04 : Machine cell, P05 : Machine cell variant (autre photo), tous OK d'emblée.
- La webcam EPI (sécurité) est analysée par le serveur de C3·P06.
Dans la fenêtre de chaque poste, on voit chaque appel aux modèles :
    POST /api/models/workstation/check   puis   POST /api/models/quality/classify

Si PowerShell refuse le script : double-cliquer sur demo\start.bat, ou
    powershell -ExecutionPolicy Bypass -File demo\start.ps1 -Stations 3

Espace AI leader (cycle de vie des modèles, Ctrl+O dans l'interface) : son serveur
(mlops/, port 8040) démarre aussi, avec son propre environnement Python .venv-mlops
(mlflow, databricks-sdk). Il lit l'espace Databricks de l'équipe : se connecter une fois
avec  databricks auth login --profile ARGOS . Réglages locaux éventuels (jamais versionnés) :
hovis.local.env à la racine, lignes CLE=VALEUR. -NoAiLeader : ne pas le démarrer.

-Here : tous les serveurs dans CE terminal (journaux mêlés, chaque ligne préfixée par le
serveur), au lieu d'une fenêtre par serveur. Ctrl+C arrête alors tout.
    .\demo\start.ps1 -Stations 2 -Mode auto -Here

Pour arrêter : fermer les fenêtres (ou Ctrl+C dans chacune) ; avec -Here, Ctrl+C.
Si un port (8000 à 8006, 8040, 5173) est déjà pris, le processus qui l'occupe est arrêté d'abord.
#>
param(
    [ValidateRange(1, 6)][int]$Stations = 1,
    [ValidateSet("manuel", "auto")][string]$Mode = "manuel",
    [switch]$NoSafety,
    [switch]$NoAiLeader,
    [switch]$Here
)

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$ui = Join-Path $repo "argos-ui"
$mlopsPython = Join-Path $repo ".venv-mlops\Scripts\python.exe"
$order = @("C3·P06", "C3·P01", "C3·P02", "C3·P03", "C3·P04", "C3·P05")

if (-not (Test-Path $python)) {
    Write-Error "Environnement Python introuvable : $python (créer le venv et faire pip install -e .)"
    exit 1
}
# Ports déjà pris (ancienne démo restée ouverte, autre serveur) : on arrête le processus
# qui les occupe, puis on les réutilise.
foreach ($port in @(8000..8006) + 8040 + 5173) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $owners) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Port $port occupé par $($proc.ProcessName) (PID $id) : arrêt."
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        }
    }
    for ($i = 0; $i -lt 20 -and (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue); $i++) {
        Start-Sleep -Milliseconds 250
    }
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        Write-Error "Impossible de libérer le port $port (droits administrateur nécessaires ?)."
        exit 1
    }
}

# Mode NOK : manuel = une pièce NOK arrête la ligne jusqu'à la réponse de l'opérateur
# (CONFIRMER / LAISSER PASSER) ; auto = l'opérateur n'est pas sollicité, la ligne continue.
$qualityMode = if ($Mode -eq "auto") { "auto" } else { "manual" }

# Un serveur : dans sa propre fenêtre (défaut) ou dans ce terminal (-Here).
$procs = @()
function Start-Server([string]$title, [string]$dir, [hashtable]$vars, [string]$exe, [string[]]$arguments) {
    if ($Here) {
        $saved = @{}
        foreach ($k in $vars.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k); Set-Item "Env:$k" $vars[$k] }
        $script:procs += Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $dir -NoNewWindow -PassThru
        foreach ($k in $vars.Keys) { if ($null -eq $saved[$k]) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue } else { Set-Item "Env:$k" $saved[$k] } }
        Write-Host "[$title] démarré (PID $($script:procs[-1].Id))"
    } else {
        $sets = ($vars.Keys | ForEach-Object { "`$env:$_ = '$($vars[$_])'" }) -join '; '
        Start-Process powershell -WorkingDirectory $dir -ArgumentList @(
            "-NoExit", "-Command",
            "`$Host.UI.RawUI.WindowTitle = 'HOVIS - $title'; $sets; & '$exe' $($arguments -join ' ')"
        )
    }
}

# 1. Un serveur par poste actif (chacun charge ses modèles : environ 20 s)
for ($k = 0; $k -lt $Stations; $k++) {
    $station = $order[$k]
    $port = 8001 + $k
    $safety = if ($k -eq 0 -and -not $NoSafety) { "1" } else { "0" }  # la webcam = C3·P06
    Start-Server "poste $station ($port)" $repo @{
        STATION_ID = $station; PROFILE = "$k"; PORT = "$port"; SAFETY = $safety
        QUALITY_MODE = $qualityMode; PYTHONIOENCODING = "utf-8"
    } $python @("-m", "uvicorn", "demo.station_server:app", "--port", "$port", "--host", "127.0.0.1")
}

# 2. Serveur de la cellule C3 (port 8000) : relaie vers les postes, vue team leader
Start-Server "cellule C3 (8000)" $repo @{ ACTIVE_STATIONS = "$Stations"; PYTHONIOENCODING = "utf-8" } `
    $python @("-m", "uvicorn", "demo.cell_server:app", "--port", "8000", "--host", "127.0.0.1")

# 3. Serveur AI leader (mlops/, port 8040) : cycle de vie des modèles, lu dans Databricks
if (-not $NoAiLeader) {
    if (Test-Path $mlopsPython) {
        $vars = @{ MLFLOW_DISABLE_AGENT_HINT = "1"; PYTHONIOENCODING = "utf-8" }
        $localEnv = Join-Path $repo "hovis.local.env"  # réglages locaux (jamais versionnés)
        if (Test-Path $localEnv) {
            Get-Content $localEnv | Where-Object { $_ -match '^\s*[A-Z_][A-Z0-9_]*\s*=' } | ForEach-Object {
                $key, $value = $_ -split '=', 2
                $vars[$key.Trim()] = $value.Trim()
            }
        }
        Start-Server "AI leader (8040)" $repo $vars `
            $mlopsPython @("-m", "uvicorn", "mlops.api.app:app", "--port", "8040", "--host", "127.0.0.1")
    } else {
        Write-Warning "Espace AI leader non démarré : environnement $mlopsPython absent (voir demo\README.md)."
    }
}

# 4. Interface argos-ui en mode live (installe les dépendances la première fois)
if (-not (Test-Path (Join-Path $ui "node_modules"))) {
    Push-Location $ui
    npm install --no-audit --no-fund
    Pop-Location
}
Start-Server "interface (5173)" $ui @{ VITE_USE_MOCK = "false" } "npx.cmd" @("vite", "--port", "5173", "--host", "127.0.0.1")

Write-Host "Postes actifs : $($order[0..($Stations - 1)] -join ', ') ; les autres : pas d'activité."
Write-Host "Mode NOK : $Mode$(if ($Mode -eq 'auto') { ' (la ligne continue, opérateur non sollicité)' } else { " (une pièce NOK attend CONFIRMER / LAISSER PASSER)" })"
Write-Host "Démarrage... le navigateur s'ouvre dans quelques secondes (modèles prêts en ~20 s)."
Write-Host "Connexion : n'importe quel identifiant = opérateur ; c.diaz@hutchinson.com = superviseur."
Write-Host "Clic sur le logo HOVIS = lancer / relancer le poste affiché (chaque poste se lance à la main) ; Ctrl+M = vue superviseur ; Ctrl+P = poste suivant ; Ctrl+O = espace AI leader."
Start-Sleep -Seconds 8
Start-Process "http://localhost:5173"

if ($Here) {
    # Tous les serveurs tournent dans ce terminal : on attend ; Ctrl+C (ou la fin d'un
    # serveur) arrête tout, processus enfants compris.
    Write-Host "Tous les serveurs tournent dans ce terminal. Ctrl+C pour tout arrêter."
    try {
        while (@($procs | Where-Object { -not $_.HasExited }).Count -eq $procs.Count) { Start-Sleep -Seconds 1 }
        Write-Warning "Un serveur s'est arrêté : arrêt des autres."
    } finally {
        foreach ($p in $procs) { & taskkill.exe /PID $p.Id /T /F 2>$null | Out-Null }
        Write-Host "Serveurs arrêtés."
    }
}
