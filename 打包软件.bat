@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 研海寻踪 · 打包
echo ============================================
echo   打包研海寻踪（电脑版 / 手机版共用同一个 exe）
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo 没找到 .venv，先运行「安装产品依赖.bat」。
  pause
  exit /b 1
)

echo [1/2] 构建前端…
pushd frontend
call npm run build
if errorlevel 1 (
  echo 前端构建失败，先修好再打包。
  popd
  pause
  exit /b 1
)
popd

echo.
echo [2/2] 打 exe…
".venv\Scripts\python.exe" "scripts\打包\构建桌面版.py"
if errorlevel 1 (
  pause
  exit /b 1
)

echo.
echo 打完收工。产物在 release\ 下。
echo 自检一次：release\研海寻踪.exe --check --no-browser
pause
