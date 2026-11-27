<#
Démarre la démo HOVIS : serveur du scénario (port 8000) et interface argos-ui (port 5173),
chacun dans sa fenêtre, puis ouvre le navigateur.

    .\demo\start.ps1              # avec l'analyse sécurité EPI (webcam), si ses poids sont là
    .\demo\start.ps1 -NoSafety    # sans l'analyse webcam (démo centrée qualité)

Si PowerShell refuse le script : double-cliquer sur demo\start.bat, ou
    powershell -ExecutionPolicy Bypass -File demo\start.ps1

Pour arrêter : fermer les deux fenêtres (ou Ctrl+C dans chacune).
#>
param([switch]$NoSafety)

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$ui = Join-Path $repo "argos-ui"

if (-not (Test-Path $python)) {
    Write-Error "Environnement Python introuvable : $python (créer le venv et faire pip install -e .)"
    exit 1
}
foreach ($port in 8000, 5173) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        Write-Error "Le port $port est déjà utilisé : un serveur tourne déjà ? Fermez-le d'abord."
        exit 1
    }
}

$safety = if ($NoSafety) { "0" } else { "1" }

# 1. Serveur du scénario (charge les modèles : environ 20 s avant d'être prêt)
Start-Process powershell -WorkingDirectory $repo -ArgumentList @(
    "-NoExit", "-Command",
    "`$Host.UI.RawUI.WindowTitle = 'HOVIS - serveur scenario (8000)'; `$env:SAFETY = '$safety'; & '$python' -m uvicorn demo.scenario:app --port 8000 --host 127.0.0.1"
)

# 2. Interface argos-ui en mode live (installe les dépendances la première fois)
if (-not (Test-Path (Join-Path $ui "node_modules"))) {
    Push-Location $ui
    npm install --no-audit --no-fund
    Pop-Location
}
Start-Process powershell -WorkingDirectory $ui -ArgumentList @(
    "-NoExit", "-Command",
    "`$Host.UI.RawUI.WindowTitle = 'HOVIS - interface (5173)'; `$env:VITE_USE_MOCK = 'false'; npx vite --port 5173 --host 127.0.0.1"
)

Write-Host "Démarrage... le navigateur s'ouvre dans quelques secondes."
Write-Host "Connexion : n'importe quel identifiant = opérateur ; c.diaz@hutchinson.com = superviseur."
Write-Host "Clic sur le logo HOVIS = lancer / relancer la simulation ; Ctrl+M = vue superviseur."
Start-Sleep -Seconds 8
Start-Process "http://localhost:5173"
