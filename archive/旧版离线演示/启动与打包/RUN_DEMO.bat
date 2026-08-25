@echo off
title Yanhai Demo Launcher
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_demo.ps1"
set "DEMO_EXIT=%ERRORLEVEL%"
if "%DEMO_EXIT%"=="2" (
  echo.
  echo The backend is ready, but Windows blocked automatic browser launch.
  echo Open this address manually: http://127.0.0.1:8765/
  echo You can also double-click OPEN_DEMO.url.
  pause
  exit /b 0
)
if not "%DEMO_EXIT%"=="0" (
  echo.
  echo Startup failed. Install Python 3.11+ or read docs\16_demo_distribution.md.
  pause
  exit /b %DEMO_EXIT%
)
echo.
echo The Demo backend is ready.
echo If no browser appears, open: http://127.0.0.1:8765/
echo Or double-click OPEN_DEMO.url.
powershell.exe -NoProfile -Command "Start-Sleep -Seconds 8"
