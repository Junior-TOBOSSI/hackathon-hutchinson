<#
.SYNOPSIS
  Starts (or stops) the unified HOVIS reference instance: integrated gateway (Core + MLOps +
  Deployment), Edge (Production Engine) and the argos-ui frontend (AI Leader + industrial live).

.DESCRIPTION
  - Remote training launches stay DISABLED (HOVIS_TRAINING_REMOTE removed) and the retraining
    scheduler stays DISABLED (HOVIS_RETRAIN_SCHEDULER removed): this script never enables them.
  - Only the processes it started (PIDs recorded in var/unified/pids.json) are stopped by
    -Stop, together with their child processes (uvicorn launched through a venv starts a child
    interpreter). No other Python / Node process of the machine is touched.
  - Refuses to start when a port is busy and shows which process holds it.
  - Checks that Vite really serves THIS worktree with the live flags (no mock UI behind a 200).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start_hovis_unified.ps1
  powershell -ExecutionPolicy Bypass -File scripts\start_hovis_unified.ps1 -Stop
  powershell -ExecutionPolicy Bypass -File scripts\start_hovis_unified.ps1 -Status
#>
[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$Status,
    [int]$GatewayPort = 8040,
    [int]$EdgePort = 18040,
    [int]$UiPort = 5180,
    [string]$Python = "",
    [string]$DataDir = "",
    [switch]$NoWarmup
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not $DataDir) { $DataDir = Join-Path $Root 'var\unified' }
$LogDir = Join-Path $DataDir 'logs'
$PidFile = Join-Path $DataDir 'pids.json'

function Write-Step([string]$text) { Write-Host "[hovis] $text" -ForegroundColor Cyan }
function Write-Bad([string]$text) { Write-Host "[hovis] $text" -ForegroundColor Red }

function Stop-Recorded {
    if (-not (Test-Path $PidFile)) { Write-Step 'No recorded process (pids.json absent).'; return }
    $recorded = Get-Content $PidFile -Raw | ConvertFrom-Json
    foreach ($entry in $recorded) {
        $proc = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
        if ($proc) {
            # /T stops the child interpreter started by the venv launcher as well.
            & taskkill.exe /PID $entry.pid /T /F | Out-Null
            Write-Step "Stopped $($entry.name) (PID $($entry.pid))."
        } else {
            Write-Step "$($entry.name) (PID $($entry.pid)) was not running."
        }
    }
    Remove-Item $PidFile -Force
}

function Get-PortOwner([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $conn) { return $null }
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)"
    return "PID $($conn.OwningProcess): $($p.CommandLine)"
}

function Wait-Http([string]$url, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try { return Invoke-RestMethod -Uri $url -TimeoutSec 5 } catch { Start-Sleep -Milliseconds 700 }
    }
    throw "no answer from $url after $seconds s"
}

if ($Stop) { Stop-Recorded; return }

if ($Status) {
    foreach ($p in @($GatewayPort, $EdgePort, $UiPort)) {
        $owner = Get-PortOwner $p
        if ($owner) { Write-Step "port ${p}: $owner" } else { Write-Step "port ${p}: free" }
    }
    if (Test-Path $PidFile) { Get-Content $PidFile -Raw | Write-Host }
    return
}

# ------------------------------------------------------------------ checks
Set-Location $Root
$branch = (& git -C $Root rev-parse --abbrev-ref HEAD).Trim()
Write-Step "Worktree $Root, branch $branch, commit $((& git -C $Root rev-parse --short HEAD).Trim())"
if ($branch -ne 'feat/hovis-unified') { Write-Bad "WARNING: expected branch feat/hovis-unified." }

if (-not $Python) {
    $Python = if ($env:HOVIS_PYTHON) { $env:HOVIS_PYTHON } else { Join-Path $env:USERPROFILE 'ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe' }
}
if (-not (Test-Path $Python)) { throw "Python not found: $Python (set -Python or HOVIS_PYTHON)" }
$env:MLFLOW_DISABLE_AGENT_HINT = '1'
# PowerShell 5.1 turns any stderr line of a native command into an error under 'Stop'.
$ErrorActionPreference = 'Continue'
& $Python -c "import fastapi, uvicorn, mlflow, databricks.sdk" 2>$null | Out-Null
$pythonOk = $LASTEXITCODE -eq 0
$ErrorActionPreference = 'Stop'
if (-not $pythonOk) { throw "Python environment $Python lacks fastapi / uvicorn / mlflow / databricks-sdk" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'node is not installed' }
$vite = Join-Path $Root 'argos-ui\node_modules\vite\bin\vite.js'
if (-not (Test-Path $vite)) { throw "argos-ui dependencies missing: run 'npm ci' in $Root\argos-ui" }

foreach ($p in @($GatewayPort, $EdgePort, $UiPort)) {
    $owner = Get-PortOwner $p
    if ($owner) { throw "port $p is busy ($owner). Stop that instance first (-Stop if it is ours) or choose other ports." }
}

New-Item -ItemType Directory -Force -Path $DataDir, $LogDir | Out-Null

# Optional local configuration (never versioned): KEY=VALUE lines in hovis.local.env.
$localEnv = Join-Path $Root 'hovis.local.env'
if (Test-Path $localEnv) {
    Get-Content $localEnv | Where-Object { $_ -match '^\s*[A-Z_][A-Z0-9_]*\s*=' } | ForEach-Object {
        $k, $v = $_ -split '=', 2
        Set-Item -Path "Env:$($k.Trim())" -Value $v.Trim()
    }
    Write-Step "Local configuration loaded from hovis.local.env"
}

# Safety: remote training and the automatic scheduler are NEVER enabled by this script.
foreach ($name in @('HOVIS_TRAINING_REMOTE', 'HOVIS_RETRAIN_SCHEDULER')) {
    if (Test-Path "Env:$name") { Remove-Item "Env:$name"; Write-Step "$name removed from the environment." }
}

$gateway = "http://127.0.0.1:$GatewayPort"
$edge = "http://127.0.0.1:$EdgePort"
$coreDb = if ($env:ARGOS_CORE_DB) { $env:ARGOS_CORE_DB } else { Join-Path $DataDir 'core.sqlite3' }
$edgeDb = if ($env:HOVIS_EDGE_DB) { $env:HOVIS_EDGE_DB } else { Join-Path $DataDir 'edge.sqlite3' }
foreach ($db in @($coreDb, $edgeDb)) {
    if (Test-Path $db) { Write-Step "Existing database kept: $db" } else { Write-Step "New isolated recette database: $db" }
}

$started = @()
function Start-HovisProcess([string]$name, [string]$file, [string[]]$arguments, [string]$cwd) {
    $out = Join-Path $LogDir "$name.log"
    $err = Join-Path $LogDir "$name.err.log"
    $p = Start-Process -FilePath $file -ArgumentList $arguments -WorkingDirectory $cwd -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    $script:started += [pscustomobject]@{ name = $name; pid = $p.Id; log = $err }
    $script:started | ConvertTo-Json | Set-Content -Path $PidFile -Encoding utf8
    Write-Step "$name started (PID $($p.Id)), logs $err"
}

try {
    # ------------------------------------------------------------------ gateway (Core + MLOps)
    $env:ARGOS_CORE_DB = $coreDb
    $env:HOVIS_CORE_URL = $gateway          # Monitoring reads the Core of THIS instance
    $env:MLFLOW_DISABLE_AGENT_HINT = '1'
    $env:HOVIS_PERF_COUNTERS = '1'       # read-only remote-call counters (/api/mlops/_perf)
    if ($NoWarmup) { Remove-Item Env:HOVIS_MLOPS_WARMUP -ErrorAction SilentlyContinue } else { $env:HOVIS_MLOPS_WARMUP = '1' }
    Start-HovisProcess 'gateway' $Python @('-m', 'uvicorn', 'mlops.api.platform:app', '--host', '127.0.0.1', '--port', "$GatewayPort") $Root
    $null = Wait-Http "$gateway/health" 90

    # ------------------------------------------------------------------ Edge (Production Engine)
    $env:DB_PATH = $edgeDb
    $env:PIPELINE_ENABLED = 'false'
    $env:SOURCE = 'synthetic'
    $env:ARGOS_CORE_URL = $gateway
    Start-HovisProcess 'edge' $Python @('-m', 'uvicorn', 'visionhub.argos_app:app', '--host', '127.0.0.1', '--port', "$EdgePort") $Root
    $null = Wait-Http "$edge/health" 60

    # ------------------------------------------------------------------ frontend
    $env:VITE_USE_MOCK = 'true'            # login / admin stay demo
    $env:VITE_LIVE_AI_LEADER = 'true'      # AI Leader on the real backend
    $env:VITE_LIVE_INDUSTRIAL = 'true'     # Operator / Supervisor / Cellule / PosteDetail on Core + Edge
    $env:ARGOS_API_TARGET = $gateway
    $env:ARGOS_EDGE_TARGET = $edge
    $node = (Get-Command node).Source
    Start-HovisProcess 'ui' $node @($vite, '--host', '127.0.0.1', '--port', "$UiPort", '--strictPort') (Join-Path $Root 'argos-ui')
    $ui = "http://127.0.0.1:$UiPort"
    $null = Wait-Http "$ui/" 60

    # ------------------------------------------------------------------ verifications
    $guard = Wait-Http "$gateway/api/mlops/training/launch-guard" 30
    if ($guard.remote_launch_enabled) { throw 'remote training launch is ENABLED: refusing this instance' }
    $sched = Wait-Http "$gateway/api/mlops/retraining/scheduler" 30
    if ($sched.enabled) { throw 'retraining scheduler is ENABLED: refusing this instance' }
    # The UI must be THIS worktree with the live flags (the old mock UI also answers 200).
    $client = Invoke-WebRequest -Uri "$ui/src/api/client.ts" -UseBasicParsing -TimeoutSec 30
    if ($client.Content -notmatch '"VITE_LIVE_AI_LEADER":\s*"true"' -or $client.Content -notmatch '"VITE_LIVE_INDUSTRIAL":\s*"true"') {
        throw 'the UI does not run with VITE_LIVE_AI_LEADER / VITE_LIVE_INDUSTRIAL = true'
    }
    $null = Invoke-WebRequest -Uri "$ui/src/pages/ai-leader/training/policies/PoliciesView.tsx" -UseBasicParsing -TimeoutSec 30
    $proxied = Invoke-RestMethod -Uri "$ui/api/mlops/training/launch-guard" -TimeoutSec 30
    if ($proxied.remote_launch_enabled) { throw 'the UI proxy reaches a gateway with remote launches enabled' }

    Write-Host ''
    Write-Step 'HOVIS unified instance is running.'
    Write-Step "  Login (single recette URL) : $ui/"
    Write-Step "  AI Leader                  : $ui/ai-leader"
    Write-Step "  Training policies          : $ui/ai-leader?section=training&view=policies"
    Write-Step "  Monitoring                 : $ui/ai-leader?section=monitoring"
    Write-Step "  Supervisor / Operator      : $ui/superviseur  |  $ui/operateur"
    Write-Step "  Gateway API docs           : $gateway/docs"
    Write-Step "  Edge                       : $edge/health"
    Write-Step "  Remote training: disabled  |  Retraining scheduler: disabled"
    Write-Step "  Stop with: powershell -ExecutionPolicy Bypass -File scripts\start_hovis_unified.ps1 -Stop"
}
catch {
    Write-Bad "Start failed: $($_.Exception.Message)"
    Write-Bad 'Stopping the processes started by this run.'
    Stop-Recorded
    exit 1
}
