<#
.SYNOPSIS
    Start ARGOS for the live AI Leader demo: backend gateway (Core + MLOps, 127.0.0.1:8020)
    and argos-ui (127.0.0.1:5174), each in its own PowerShell window.

.DESCRIPTION
    - Gateway: mlops.api.platform (Core of Codex unchanged + MLOps router under /api),
      run with the ARGOS MLOps venv (MLflow, Databricks SDK, CLI profile ARGOS).
    - argos-ui: VITE_LIVE_AI_LEADER=true -> only the AI Leader screen uses real data;
      Operator / Supervisor / Admin keep their demo data (badge "Démo · données simulées").
    Nothing is exposed outside localhost. No Databricks resource is created or started:
    the SQL warehouse is never started automatically.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File mlops\scripts\start_argos_live.ps1
    # then open http://127.0.0.1:5174  (identifiant a.noui@hutchinson.com, rôle AI Leader)
#>
param(
    [string]$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$MlopsHome = $(if ($env:ARGOS_MLOPS_HOME) { $env:ARGOS_MLOPS_HOME } else { Join-Path $env:USERPROFILE "ARGOS_MLOPS_LOCAL" }),
    [int]$ApiPort = 8020,
    [int]$UiPort = 5174
)
$python = Join-Path $MlopsHome ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "MLOps venv not found: $python" }
foreach ($port in $ApiPort, $UiPort) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port already in use." }
}

$api = @"
Set-Location '$Repo'
`$env:ARGOS_CORE_DB = 'var/argos-integration-core.sqlite3'
`$env:MLFLOW_DISABLE_AGENT_HINT = '1'
`$env:HOVIS_MLOPS_WARMUP = '1'
& '$python' -m uvicorn mlops.api.platform:app --host 127.0.0.1 --port $ApiPort
"@
$ui = @"
Set-Location '$Repo\argos-ui'
if (-not (Test-Path node_modules)) { npm ci --no-audit --no-fund }
`$env:VITE_LIVE_AI_LEADER = 'true'
`$env:ARGOS_API_TARGET = 'http://127.0.0.1:$ApiPort'
npx vite --host 127.0.0.1 --port $UiPort --strictPort
"@
Start-Process powershell -ArgumentList "-NoExit", "-Command", $api
Start-Process powershell -ArgumentList "-NoExit", "-Command", $ui
Write-Host "Backend : http://127.0.0.1:$ApiPort/docs"
Write-Host "ARGOS   : http://127.0.0.1:$UiPort  (AI Leader : a.noui@hutchinson.com)"
