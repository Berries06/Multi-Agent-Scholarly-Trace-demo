@echo off
title Yanhai Demo Stopper
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_demo.ps1"
if errorlevel 1 pause
