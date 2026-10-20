@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 研海寻踪 · 鸿蒙模拟器

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\环境\启动鸿蒙模拟器.ps1"
if errorlevel 1 (
  echo.
  echo 模拟器没起来，看上面那几行提示。
  pause
)
