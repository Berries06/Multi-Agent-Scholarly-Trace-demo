@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  研海寻踪一键启动（DeepSeek）
echo ============================================
if not exist ".venv\Scripts\python.exe" (
  echo 未找到 .venv，请先双击“安装产品依赖.bat”。
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\环境\启动产品.ps1" -Provider free-deepseek
if errorlevel 1 (
  echo.
  echo 启动失败，请根据上方提示处理。
  pause
  exit /b 1
)
echo 启动窗口将在 3 秒后关闭，网页服务会继续运行。
timeout /t 3 >nul
