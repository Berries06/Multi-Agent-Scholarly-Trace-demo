@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 研海寻踪 · 手机版
echo ============================================
echo   研海寻踪 手机版
echo   手机和这台电脑连同一个 WiFi，就能打开
echo ============================================
echo.

if exist "release\研海寻踪.exe" (
  "release\研海寻踪.exe" --lan
  goto :done
)

if exist "研海寻踪.exe" (
  "研海寻踪.exe" --lan
  goto :done
)

if not exist ".venv\Scripts\python.exe" (
  echo 没找到打包好的 release\研海寻踪.exe，也没有 .venv。
  echo 先在根目录运行「安装产品依赖.bat」，或者先打一次包：
  echo   .venv\Scripts\python.exe scripts\打包\构建桌面版.py
  pause
  goto :done
)

echo 没有 release\研海寻踪.exe，直接用源码启动。
.venv\Scripts\python.exe "src\yanhai\desktop.py" --lan

:done
if errorlevel 1 pause
