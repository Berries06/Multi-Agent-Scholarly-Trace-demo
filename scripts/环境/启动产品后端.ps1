param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8766,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到 .venv；请先创建统一环境。"
}

$Arguments = @("-m", "uvicorn", "yanhai.api:app", "--host", $HostAddress, "--port", "$Port")
if ($Reload) { $Arguments += "--reload" }
Push-Location $ProjectRoot
try { & $Python @Arguments } finally { Pop-Location }
