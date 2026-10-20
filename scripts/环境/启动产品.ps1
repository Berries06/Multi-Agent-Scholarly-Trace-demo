param(
    [string]$HostAddress = "127.0.0.1",
    [int]$BackendPort = 8766,
    [int]$FrontendPort = 5173,
    [ValidateSet("free-deepseek", "mock")]
    [string]$Provider = "free-deepseek",
    [ValidateRange(3, 60)]
    [int]$StartupTimeoutSeconds = 20,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$ViteEntry = Join-Path $FrontendRoot "node_modules\vite\bin\vite.js"
$RuntimeRoot = Join-Path $ProjectRoot ".runtime\product-startup"
$BackendUrl = "http://${HostAddress}:$BackendPort"
$FrontendUrl = "http://${HostAddress}:$FrontendPort"

function Get-ListeningProcessId([int]$Port) {
    foreach ($entry in (netstat -ano -p TCP)) {
        if ($entry -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            return [int]$Matches[1]
        }
    }
    return $null
}

function Wait-PortReleased([int]$Port) {
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (-not (Get-ListeningProcessId $Port)) { return }
        Start-Sleep -Milliseconds 150
    }
    throw "Port $Port was not released in time."
}

function Stop-RecognizedBackend {
    $processId = Get-ListeningProcessId $BackendPort
    if (-not $processId) { return }
    try {
        $health = Invoke-RestMethod -Uri "$BackendUrl/api/health" -TimeoutSec 2
    } catch {
        throw "Port $BackendPort is occupied by an unrecognized process (PID $processId)."
    }
    if ($health.service -ne "yanhai-api") {
        throw "Port $BackendPort is occupied by another service (PID $processId)."
    }
    Write-Host "Replacing the existing Yanhai backend (PID $processId)..."
    Stop-Process -Id $processId -Force
    Wait-PortReleased $BackendPort
}

function Stop-RecognizedFrontend {
    $processId = Get-ListeningProcessId $FrontendPort
    if (-not $processId) { return }
    try {
        $page = Invoke-WebRequest -Uri "$FrontendUrl/" -UseBasicParsing -TimeoutSec 2
    } catch {
        throw "Port $FrontendPort is occupied by an unrecognized process (PID $processId)."
    }
    if ($page.Content -notmatch '/src/main.tsx') {
        throw "Port $FrontendPort is occupied by another web service (PID $processId)."
    }
    Write-Host "Replacing the existing Yanhai frontend (PID $processId)..."
    Stop-Process -Id $processId -Force
    Wait-PortReleased $FrontendPort
}

function Wait-Backend([System.Diagnostics.Process]$Process) {
    $deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) { break }
        try {
            $health = Invoke-RestMethod -Uri "$BackendUrl/api/health" -TimeoutSec 1
            if ($health.status -eq "ok" -and $health.service -eq "yanhai-api") { return $health }
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    throw "Backend did not become ready within $StartupTimeoutSeconds seconds."
}

function Wait-Frontend([System.Diagnostics.Process]$Process) {
    $deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) { break }
        try {
            $page = Invoke-WebRequest -Uri "$FrontendUrl/" -UseBasicParsing -TimeoutSec 1
            if ($page.StatusCode -eq 200 -and $page.Content -match '/src/main.tsx') { return }
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    throw "Frontend did not become ready within $StartupTimeoutSeconds seconds."
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Missing .venv. Run the dependency installer first.'
}
if (-not (Test-Path -LiteralPath $ViteEntry)) {
    throw 'Missing frontend dependencies. Run the dependency installer first.'
}
$Node = Get-Command node -ErrorAction SilentlyContinue
if (-not $Node) { throw "Node.js was not found." }

if ($Provider -eq "free-deepseek") {
    $ConfiguredKey = [Environment]::GetEnvironmentVariable("YANHAI_DEEPSEEK_KEY_FILE")
    $KeyFile = if ($ConfiguredKey) { $ConfiguredKey } else { Join-Path $ProjectRoot "secret\DeepSeekAPI.txt" }
    if (-not (Test-Path -LiteralPath $KeyFile) -or (Get-Item -LiteralPath $KeyFile).Length -eq 0) {
        throw "DeepSeek key is unavailable. Check: $KeyFile"
    }
}

New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
Stop-RecognizedFrontend
Stop-RecognizedBackend

$BackendProcess = $null
$FrontendProcess = $null
try {
    Write-Host "Starting backend..."
    $BackendProcess = Start-Process `
        -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", "yanhai.api:app", "--host", $HostAddress, "--port", "$BackendPort") `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru
    $health = Wait-Backend $BackendProcess

    Write-Host "Starting frontend..."
    $FrontendProcess = Start-Process `
        -FilePath $Node.Source `
        -ArgumentList @($ViteEntry, "--host", $HostAddress, "--port", "$FrontendPort") `
        -WorkingDirectory $FrontendRoot `
        -WindowStyle Hidden `
        -PassThru
    Wait-Frontend $FrontendProcess

    $BackendListenerPid = Get-ListeningProcessId $BackendPort
    $FrontendListenerPid = Get-ListeningProcessId $FrontendPort
    Set-Content -LiteralPath (Join-Path $RuntimeRoot "backend.pid") -Value $BackendListenerPid -Encoding ascii
    Set-Content -LiteralPath (Join-Path $RuntimeRoot "frontend.pid") -Value $FrontendListenerPid -Encoding ascii

    $OpenUrl = "$FrontendUrl/?provider=$([Uri]::EscapeDataString($Provider))"
    Write-Host ""
    Write-Host "Yanhai is ready" -ForegroundColor Green
    Write-Host "Web: $OpenUrl"
    Write-Host "Provider: $(if ($Provider -eq 'free-deepseek') { 'Free DeepSeek (Flash)' } else { 'Offline rules' })"
    Write-Host "Backend: $($health.status); PID $BackendListenerPid"
    Write-Host "Frontend: ready; PID $FrontendListenerPid"
    if (-not $NoBrowser) { Start-Process $OpenUrl }
} catch {
    if ($FrontendProcess -and -not $FrontendProcess.HasExited) { Stop-Process -Id $FrontendProcess.Id -Force }
    if ($BackendProcess -and -not $BackendProcess.HasExited) { Stop-Process -Id $BackendProcess.Id -Force }
    throw
}
