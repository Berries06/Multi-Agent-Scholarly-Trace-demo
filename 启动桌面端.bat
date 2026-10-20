@echo off
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo 未找到统一环境 .venv，请先运行“安装产品依赖.bat”。
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\环境\启动桌面端.ps1"
if errorlevel 1 pause
