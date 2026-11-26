<#
.SYNOPSIS
    Check the local ARGOS MLflow server: network exposure, HTTP, UI, REST API, Python SDK,
    SQLite backend store and artifact store. Exit code 0 = everything OK.
#>
param(
    [string]$MlopsHome = $(if ($env:ARGOS_MLOPS_HOME) { $env:ARGOS_MLOPS_HOME } else { Join-Path $env:USERPROFILE "ARGOS_MLOPS_LOCAL" }),
    [int]$Port = 5000
)
$base = "http://127.0.0.1:$Port"
$failures = 0
function Report($ok, $label, $detail) {
    $mark = if ($ok) { "[OK]  " } else { "[FAIL]"; $script:failures++ }
    Write-Host ("{0} {1,-34} {2}" -f $mark, $label, $detail)
}

$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
$addresses = ($listeners.LocalAddress | Sort-Object -Unique) -join ", "
Report ($listeners.Count -gt 0) "Listening on port $Port" $addresses
Report ($listeners.Count -gt 0 -and -not ($listeners.LocalAddress | Where-Object { $_ -notin "127.0.0.1", "::1" })) "Localhost only (not public)" $addresses

try { $r = Invoke-WebRequest -UseBasicParsing "$base/health" -TimeoutSec 5; Report ($r.StatusCode -eq 200) "GET /health" $r.Content } catch { Report $false "GET /health" $_.Exception.Message }
try { $r = Invoke-WebRequest -UseBasicParsing "$base/version" -TimeoutSec 5; Report ($r.Content -eq "3.18.0") "GET /version" $r.Content } catch { Report $false "GET /version" $_.Exception.Message }
try { $r = Invoke-WebRequest -UseBasicParsing "$base/" -TimeoutSec 5; Report ($r.Content -match "<title>MLflow") "MLflow UI (GET /)" "HTTP $($r.StatusCode)" } catch { Report $false "MLflow UI (GET /)" $_.Exception.Message }
try {
    $r = Invoke-RestMethod -Method Post "$base/api/2.0/mlflow/experiments/search" -ContentType "application/json" -Body '{"max_results": 100}' -TimeoutSec 5
    Report $true "REST experiments/search" "$(@($r.experiments).Count) experiment(s)"
} catch { Report $false "REST experiments/search" $_.Exception.Message }

$db = Join-Path $MlopsHome "storage\mlflow.db"
Report (Test-Path $db) "SQLite backend store" "$db ($([math]::Round((Get-Item $db -ErrorAction SilentlyContinue).Length / 1KB)) KB)"
$artifacts = Join-Path $MlopsHome "storage\mlartifacts"
$files = @(Get-ChildItem -Recurse -File $artifacts -ErrorAction SilentlyContinue)
Report (Test-Path $artifacts) "Artifact store folder" "$artifacts ($($files.Count) file(s))"

$python = Join-Path $MlopsHome ".venv\Scripts\python.exe"
$sdk = & $python -c "import mlflow; from mlflow import MlflowClient; mlflow.set_tracking_uri('$base'); print(len(MlflowClient().search_experiments()))" 2>&1 | Select-Object -Last 1
Report ($LASTEXITCODE -eq 0) "Python SDK -> server" "$sdk experiment(s) seen by MlflowClient"

if ($failures) { Write-Host "`n$failures check(s) failed."; exit 1 }
Write-Host "`nAll checks passed. UI: $base"
