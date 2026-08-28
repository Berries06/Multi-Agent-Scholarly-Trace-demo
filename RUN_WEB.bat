@echo off
chcp 65001 >nul
echo ============================================
echo  Yanhai Web  (backend :8766 + frontend :5173)
echo ============================================
echo Starting backend in a new window...
start "yanhai-api" cmd /k "set PYTHONPATH=src&& python -m uvicorn yanhai.api:app --host 127.0.0.1 --port 8766"
echo Starting frontend in a new window...
start "yanhai-web" cmd /k "cd frontend&& npm run dev"
echo Waiting for servers...
timeout /t 8 >nul
start http://127.0.0.1:5173
echo.
echo Two windows are now running: yanhai-api and yanhai-web.
echo Keep both open. Close them to stop the demo.
pause
