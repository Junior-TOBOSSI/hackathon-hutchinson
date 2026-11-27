<#
.SYNOPSIS
    Stop the local ARGOS MLflow server started by start_mlflow.ps1 (and only it).
    Data is kept: SQLite and artifacts stay in <ARGOS_MLOPS_HOME>\storage.
#>
param(
    [string]$MlopsHome = $(if ($env:ARGOS_MLOPS_HOME) { $env:ARGOS_MLOPS_HOME } else { Join-Path $env:USERPROFILE "ARGOS_MLOPS_LOCAL" }),
    [int]$Port = 5000
)
$pidFile = Join-Path $MlopsHome "logs\mlflow-server.pid"
$serverPid = if (Test-Path $pidFile) { [int](Get-Content $pidFile) } else { $null }

if (-not $serverPid) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener -and (Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)").CommandLine -match "mlflow") {
        $serverPid = $listener.OwningProcess
    }
}
if (-not $serverPid -or -not (Get-Process -Id $serverPid -ErrorAction SilentlyContinue)) {
    Write-Host "No ARGOS MLflow server running."
    Remove-Item -ErrorAction SilentlyContinue $pidFile
    exit 0
}
# /T stops the uvicorn worker started by the mlflow CLI as well.
taskkill /PID $serverPid /T /F | Out-Null
Remove-Item -ErrorAction SilentlyContinue $pidFile
Start-Sleep -Seconds 1
$still = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($still) { Write-Warning "Port $Port still in use by PID $($still[0].OwningProcess)."; exit 1 }
Write-Host "MLflow stopped (PID $serverPid). Data kept in $(Join-Path $MlopsHome 'storage')."
