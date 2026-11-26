<#
.SYNOPSIS
    Start the local ARGOS MLflow tracking server (127.0.0.1 only), in the background.

.DESCRIPTION
    Backend store : SQLite      <ARGOS_MLOPS_HOME>\storage\mlflow.db
    Artifact store: local folder <ARGOS_MLOPS_HOME>\storage\mlartifacts, served by the
                    tracking server itself (--serve-artifacts): clients never touch the
                    folder directly, they upload/download through HTTP.
    Logs          : <ARGOS_MLOPS_HOME>\logs\mlflow-server.{out,err}.log
    PID file      : <ARGOS_MLOPS_HOME>\logs\mlflow-server.pid

    All paths are absolute, so the script works from any current directory.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File mlops\scripts\start_mlflow.ps1
#>
param(
    [string]$MlopsHome = $(if ($env:ARGOS_MLOPS_HOME) { $env:ARGOS_MLOPS_HOME } else { Join-Path $env:USERPROFILE "ARGOS_MLOPS_LOCAL" }),
    [int]$Port = 5000,
    [int]$TimeoutSeconds = 90
)
$ErrorActionPreference = "Stop"

$mlflowExe = Join-Path $MlopsHome ".venv\Scripts\mlflow.exe"
$storage = Join-Path $MlopsHome "storage"
$artifacts = Join-Path $storage "mlartifacts"
$logs = Join-Path $MlopsHome "logs"
$pidFile = Join-Path $logs "mlflow-server.pid"
if (-not (Test-Path $mlflowExe)) { throw "MLflow not found: $mlflowExe (create the ARGOS MLOps venv first)" }
New-Item -ItemType Directory -Force $storage, $artifacts, $logs | Out-Null

# Already running?
$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if ($owner.CommandLine -match "mlflow") {
        Write-Host "MLflow already listening on $($listener.LocalAddress):$Port (PID $($listener.OwningProcess))."
        exit 0
    }
    throw "Port $Port is used by another program (PID $($listener.OwningProcess)). Use -Port <other>."
}

# SQLAlchemy wants sqlite:///C:/...  ; MLflow wants a file:/// URI for a local Windows folder.
$backendUri = "sqlite:///" + ((Join-Path $storage "mlflow.db") -replace "\\", "/")
$artifactsUri = "file:///" + ($artifacts -replace "\\", "/")

$arguments = @(
    "server",
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--workers", "1",
    "--backend-store-uri", $backendUri,
    "--serve-artifacts",
    "--artifacts-destination", $artifactsUri
)

foreach ($stream in "out", "err") {
    $log = Join-Path $logs "mlflow-server.$stream.log"
    if (Test-Path $log) { Move-Item -Force $log "$log.prev" }
}

# Launched through WMI (Win32_Process.Create) rather than Start-Process: the server must
# not inherit the caller's console/pipe handles, otherwise `start_mlflow.ps1 | ...` would
# wait forever for the long-running server to close them.
$quoted = ($arguments | ForEach-Object { '"{0}"' -f $_ }) -join " "
$outLog = Join-Path $logs "mlflow-server.out.log"
$errLog = Join-Path $logs "mlflow-server.err.log"
$commandLine = 'cmd.exe /d /c "set MLFLOW_DISABLE_AGENT_HINT=1&& "{0}" {1} 1>"{2}" 2>"{3}""' -f $mlflowExe, $quoted, $outLog, $errLog
$hidden = New-CimInstance -ClassName Win32_ProcessStartup -Property @{ ShowWindow = [uint16]0 } -ClientOnly
$created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $commandLine; CurrentDirectory = $MlopsHome; ProcessStartupInformation = $hidden
}
if ($created.ReturnValue -ne 0) { throw "Could not start MLflow (Win32_Process.Create returned $($created.ReturnValue))" }
$process = Get-Process -Id $created.ProcessId
$process.Id | Set-Content -Encoding ascii $pidFile

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/health" -TimeoutSec 2
        if ($health.StatusCode -eq 200) {
            Write-Host "MLflow started (PID $($process.Id)) on http://127.0.0.1:$Port"
            Write-Host "  backend store : $backendUri"
            Write-Host "  artifact store: $artifactsUri (proxied by the server)"
            Write-Host "  logs          : $logs"
            exit 0
        }
    } catch { Start-Sleep -Milliseconds 700 }
    if ($process.HasExited) { break }
}
Write-Error "MLflow did not become healthy. See $(Join-Path $logs 'mlflow-server.err.log')"
exit 1
