@echo off
chcp 65001 >nul
echo ============================================
echo  研海寻踪产品依赖安装（FastAPI + React）
echo ============================================
echo.
echo 创建唯一 Python 环境 .venv，并安装产品、测试、桌面和实验台依赖...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\环境\创建统一环境.ps1"
if errorlevel 1 (
  echo 统一环境安装失败，请检查网络、Python 3.12 和 Node.js。
  pause
  exit /b 1
)
echo.
echo 安装完成。现在可双击“启动产品.bat”。
pause
