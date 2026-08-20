@echo off
chcp 65001 >nul
echo ============================================
echo  Yanhai Web one-time setup (backend + frontend)
echo ============================================
echo.
echo [1/2] Installing backend deps (fastapi/uvicorn/python-multipart)...
python -m pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" "python-multipart>=0.0.9"
if errorlevel 1 (
  echo Backend deps install FAILED. Check network / python on PATH.
  pause
  exit /b 1
)
echo.
echo [2/2] Installing frontend deps via npm (takes a few minutes)...
cd frontend
cmd /c npm install
if errorlevel 1 (
  echo Frontend deps install FAILED. Check Node.js and network.
  pause
  exit /b 1
)
cd ..
echo.
echo Setup done. Now double-click RUN_WEB.bat to start.
pause
