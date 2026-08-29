@echo off
setlocal
cd /d "%~dp0"

if /i "%~1"=="--dsh" goto run_dsh

set "YANHAI_PYTHON=.venv-lab\Scripts\python.exe"
if exist "%YANHAI_PYTHON%" goto run_direct

where py >nul 2>nul
if not errorlevel 1 (
  set "YANHAI_PYTHON=py -3"
  goto run_direct
)

where python >nul 2>nul
if not errorlevel 1 (
  set "YANHAI_PYTHON=python"
  goto run_direct
)

echo [ERROR] Python 3.11+ was not found. Create .venv-lab or install Python.
exit /b 1

:run_direct
echo Running six versioned public experiment protocols...
%YANHAI_PYTHON% -m tests.experiments.run_all --repetitions 1
if errorlevel 1 exit /b %errorlevel%
call RUN_MLFLOW.bat
if errorlevel 1 exit /b %errorlevel%
echo.
echo Verified artifacts are under outputs\experiments\ and synchronized to MLflow.
echo Experiment Ledger: http://127.0.0.1:5173/  ^> 04 Experiment Ledger
echo MLflow:           http://127.0.0.1:5000/
exit /b 0

:run_dsh
echo Delegating the same repository protocol to the yanhai DSH profile...
dsh --profile yanhai "Read docs/协作与运维/DSH实验执行协议.md and tests/experiments/AGENT_RUNBOOK.md, then run the public experiment suite exactly once and synchronize every verified run to MLflow. Do not change frozen configs, do not hide failures, and report every artifact path and verification status."
exit /b %errorlevel%
