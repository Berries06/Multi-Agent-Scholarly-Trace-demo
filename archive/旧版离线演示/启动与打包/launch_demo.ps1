param(
    [switch]$NoBrowser,
    [ValidateRange(2, 60)]
    [int]$StartupTimeoutSeconds = 12
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputsDirectory = Join-Path $projectRoot "outputs"
$pidPath = Join-Path $outputsDirectory "demo.pid"
$url = "http://127.0.0.1:8765/"
$healthUri = "${url}api/health"
$serverPid = $null
$reused = $false

try {
    $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 1
    if (
        $health.status -eq "ok" -and
        $health.PSObject.Properties.Name -contains "domains" -and
        $health.PSObject.Properties.Name -contains "default_domain"
    ) {
        $reused = $true
    } else {
        throw "Port 8765 is already serving an unrelated process."
    }
} catch [System.Net.WebException] {
    $result = & (Join-Path $PSScriptRoot "start_demo.ps1") `
        -Background `
        -StartupTimeoutSeconds $StartupTimeoutSeconds
    $serverPid = [int]$result.Pid
    New-Item -ItemType Directory -Path $outputsDirectory -Force | Out-Null
    Set-Content -LiteralPath $pidPath -Value $serverPid -Encoding Ascii
}

$browserOpened = $NoBrowser
$browserError = $null
if (-not $NoBrowser) {
    try {
        $explorerPath = Join-Path $env:SystemRoot "explorer.exe"
        Start-Process `
            -FilePath $explorerPath `
            -ArgumentList @($url) `
            -ErrorAction Stop
        $browserOpened = $true
    } catch {
        $browserError = $_.Exception.Message
        try {
            $startInfo = New-Object System.Diagnostics.ProcessStartInfo
            $startInfo.FileName = $url
            $startInfo.UseShellExecute = $true
            $null = [System.Diagnostics.Process]::Start($startInfo)
            $browserOpened = $true
        } catch {
            $browserError = $_.Exception.Message
        }
    }
}

Write-Host ""
Write-Host "Yanhai Demo is ready:" -ForegroundColor Green
Write-Host "  $url"
if ($reused) {
    Write-Host "  Reused the existing local service."
} else {
    Write-Host "  Backend PID: $serverPid"
}
Write-Host "Stop the service by double-clicking STOP_DEMO.bat."

if (-not $browserOpened) {
    Write-Warning "The backend is ready, but Windows could not open the default browser: $browserError"
    Write-Host "Open manually: $url" -ForegroundColor Yellow
    Write-Host "Or double-click OPEN_DEMO.url."
    exit 2
}
