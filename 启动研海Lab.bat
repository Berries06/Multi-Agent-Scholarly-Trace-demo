@echo off
setlocal
cd /d "%~dp0"

set "PYTHONUTF8=1"

echo Starting Yanhai Lab (internal experiment console) on http://127.0.0.1:8767/ ...
echo It shares the account database and login state with the product on 8766.
echo Only accounts with is_admin can read anything here.
echo.

.venv\Scripts\python.exe -m uvicorn yanhai.lab_api:app --host 127.0.0.1 --port 8767

endlocal
