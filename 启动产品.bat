@echo off
chcp 65001 >nul
echo ============================================
echo  研海寻踪产品开发环境（后端 :8766 + 前端 :5173）
echo ============================================
echo 正在新窗口启动 FastAPI...
if not exist ".venv\Scripts\python.exe" (
  echo 未找到 .venv，请先双击“安装产品依赖.bat”。
  pause
  exit /b 1
)
start "yanhai-api" powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0scripts\环境\启动产品后端.ps1"
echo 正在新窗口启动 React 开发服务器...
start "yanhai-web" cmd /k "cd /d %~dp0frontend&& npm run dev"
echo 等待服务就绪...
timeout /t 8 >nul
start http://127.0.0.1:5173
echo.
echo 产品已启动。运行期间请保持两个服务窗口开启。
pause
