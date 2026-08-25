$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到 .venv；请先创建统一环境。"
}
Push-Location $ProjectRoot
try { & $Python -m yanhai.qt_app } finally { Pop-Location }
