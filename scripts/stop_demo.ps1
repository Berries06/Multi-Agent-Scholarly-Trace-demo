$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pidPath = Join-Path $projectRoot "outputs\demo.pid"

if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Host "No process recorded by this launcher. Close the original server window if it is still running." -ForegroundColor Yellow
    exit 0
}

$rawPid = (Get-Content -LiteralPath $pidPath -Raw).Trim()
$parsedPid = 0
if (-not [int]::TryParse($rawPid, [ref]$parsedPid)) {
    throw "outputs\demo.pid is invalid. No process was stopped."
}

$process = Get-Process -Id $parsedPid -ErrorAction SilentlyContinue
if ($process) {
    if ($process.ProcessName -notin @("python", "pythonw", "py")) {
        throw "PID $parsedPid belongs to $($process.ProcessName). No process was stopped."
    }
    Stop-Process -Id $parsedPid
    Write-Host "Stopped Yanhai Demo (PID $parsedPid)." -ForegroundColor Green
} else {
    Write-Host "The recorded Demo process has already exited." -ForegroundColor Yellow
}

Remove-Item -LiteralPath $pidPath -Force
