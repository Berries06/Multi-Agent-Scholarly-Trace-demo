@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 研海寻踪 · 停止鸿蒙模拟器

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\环境\启动鸿蒙模拟器.ps1" -Stop
timeout /t 3 >nul
