@echo off
rem Double-clic : démarre la démo HOVIS (voir start.ps1). Arguments transmis, ex. : start.bat -Stations 3 -NoSafety
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
