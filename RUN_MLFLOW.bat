@echo off
setlocal
cd /d "%~dp0"

set "YANHAI_MLFLOW_TRACKING_URI=http://127.0.0.1:5000"
set "PYTHONUTF8=1"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_mlflow.ps1" -Background
if errorlevel 1 exit /b %errorlevel%

echo Synchronizing verified Yanhai runs without re-running models...
.venv-lab\Scripts\python.exe scripts\sync_mlflow.py
if errorlevel 1 exit /b %errorlevel%

echo.
echo MLflow is ready at http://127.0.0.1:5000/
echo Yanhai remains at http://127.0.0.1:5173/
endlocal
