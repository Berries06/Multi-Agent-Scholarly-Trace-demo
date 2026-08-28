param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 5000,
    [switch]$Background,
    [ValidateRange(2, 60)]
    [int]$StartupTimeoutSeconds = 20
)

function Get-ListeningProcessId([int]$TargetPort) {
    $connection = Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($connection) {
        return [int]$connection.OwningProcess
    }
    $pattern = "^\s*TCP\s+127\.0\.0\.1:$TargetPort\s+\S+\s+LISTENING\s+(\d+)\s*$"
    $match = netstat -ano | Select-String -Pattern $pattern | Select-Object -First 1
    if ($match -and $match.Matches.Count -gt 0) {
        return [int]$match.Matches[0].Groups[1].Value
    }
    return $null
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$mlflowExecutable = Join-Path $projectRoot ".venv-lab\Scripts\mlflow.exe"
if (-not (Test-Path -LiteralPath $mlflowExecutable)) {
    throw "MLflow was not found in .venv-lab. Install with: .venv-lab\Scripts\python.exe -m pip install '.[tracking]'"
}

$stateRoot = Join-Path $projectRoot ".mlflow"
$artifactRoot = Join-Path $stateRoot "artifacts"
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$dbPath = (Join-Path $stateRoot "mlflow.db").Replace("\", "/")
$artifactPath = $artifactRoot.Replace("\", "/")
$backendUri = "sqlite:///$dbPath"
$artifactUri = "file:///$artifactPath"
$serverArguments = @(
    "server",
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--workers", "1",
    "--backend-store-uri", $backendUri,
    "--artifacts-destination", $artifactUri,
    "--allowed-hosts", "127.0.0.1:$Port,localhost:$Port"
)
$healthUri = "http://127.0.0.1:$Port/health"

try {
    $existing = Invoke-WebRequest -Uri $healthUri -TimeoutSec 2 -UseBasicParsing
    if ($existing.StatusCode -eq 200) {
        $serverPid = Get-ListeningProcessId $Port
        if ($serverPid) {
            $serverPid | Set-Content -LiteralPath (Join-Path $stateRoot "server.pid") -Encoding ASCII
        }
        [PSCustomObject]@{
            Status = "already-running"
            Url = "http://127.0.0.1:$Port/"
            Backend = $backendUri
        }
        exit 0
    }
} catch {
    # Expected when the server has not started yet.
}

if (-not $Background) {
    Write-Host "MLflow UI: http://127.0.0.1:$Port/"
    & $mlflowExecutable @serverArguments
    exit $LASTEXITCODE
}

$stdoutPath = Join-Path $stateRoot "server.out.log"
$stderrPath = Join-Path $stateRoot "server.err.log"
$process = Start-Process `
    -FilePath $mlflowExecutable `
    -ArgumentList $serverArguments `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru
$deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
while ([DateTime]::UtcNow -lt $deadline) {
    try {
        $health = Invoke-WebRequest -Uri $healthUri -TimeoutSec 2 -UseBasicParsing
        if ($health.StatusCode -eq 200) {
            Start-Sleep -Milliseconds 750
            $listenerPid = Get-ListeningProcessId $Port
            $serverPid = if ($listenerPid) { $listenerPid } else { $process.Id }
            $process.Id | Set-Content -LiteralPath (Join-Path $stateRoot "launcher.pid") -Encoding ASCII
            $serverPid | Set-Content -LiteralPath (Join-Path $stateRoot "server.pid") -Encoding ASCII
            [PSCustomObject]@{
                Status = "started"
                Pid = $serverPid
                Url = "http://127.0.0.1:$Port/"
                Backend = $backendUri
                Artifacts = $artifactUri
            }
            exit 0
        }
    } catch {
        # Keep polling until the bounded deadline.
    }
    if ($process.HasExited) {
        throw "MLflow exited during startup. Inspect .mlflow\server.err.log."
    }
    Start-Sleep -Milliseconds 250
}

if (-not $process.HasExited) {
    Stop-Process -Id $process.Id
}
throw "MLflow did not become healthy within $StartupTimeoutSeconds seconds."
