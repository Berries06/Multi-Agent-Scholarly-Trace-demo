@echo off
REM ============================================================
REM  DeepSeek Harness (dsh) 启动脚本
REM  默认地址: http://127.0.0.1:3080
REM ============================================================
setlocal

REM 设置 DSH_HOME（默认 %USERPROFILE%\.dsh，可自行修改）
if not defined DSH_HOME set "DSH_HOME=%USERPROFILE%\.dsh"

REM 若未设置 DEEPSEEK_API_KEY，则从 %DSH_HOME%\.env 读取（格式: DEEPSEEK_API_KEY=sk-...）
if not defined DEEPSEEK_API_KEY (
  if exist "%DSH_HOME%\.env" (
    for /f "usebackq tokens=1,* delims==" %%a in ("%DSH_HOME%\.env") do (
      if /i "%%a"=="DEEPSEEK_API_KEY" set "DEEPSEEK_API_KEY=%%b"
    )
  )
)

if not defined DEEPSEEK_API_KEY (
  echo [WARN] 未检测到 DEEPSEEK_API_KEY，请在「设置 -^> 模型」中手动填写，或设置环境变量。
)

echo 正在启动 DeepSeek Harness Web UI (DSH_HOME=%DSH_HOME%) ...
echo 启动后请访问: http://127.0.0.1:3080
echo 按 Ctrl+C 停止。
dsh web

endlocal
