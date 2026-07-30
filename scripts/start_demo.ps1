param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$Background,
    [ValidateRange(2, 60)]
    [int]$StartupTimeoutSeconds = 10
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$command = Get-Command python -ErrorAction SilentlyContinue
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$pythonPrefixArguments = @()

if ($command) {
    $pythonExecutable = $command.Source
} elseif ($pyLauncher) {
    $pythonExecutable = $pyLauncher.Source
    $pythonPrefixArguments = @("-3")
} elseif (Test-Path -LiteralPath $bundledPython) {
    $pythonExecutable = $bundledPython
} else {
    throw "Python 3.11+ was not found. Install Python from https://www.python.org/downloads/ and enable Add Python to PATH."
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
Write-Host "Yanhai backend: http://${HostAddress}:$Port/"

if (-not $Background) {
    & $pythonExecutable @pythonPrefixArguments -m yanhai.server --host $HostAddress --port $Port
    exit $LASTEXITCODE
}

# Do not redirect stdout/stderr here. Redirected handles can keep desktop tool
# sessions attached to the long-running child process and make startup appear
# blocked even after the server is healthy.
$process = Start-Process `
    -FilePath $pythonExecutable `
    -ArgumentList @($pythonPrefixArguments + @("-m", "yanhai.server", "--host", $HostAddress, "--port", "$Port")) `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

$deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
$healthUri = "http://${HostAddress}:$Port/api/health"
$healthy = $false

while ([DateTime]::UtcNow -lt $deadline) {
    if ($process.HasExited) {
        break
    }
    try {
        $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 1
        # A stale process on the same port can otherwise satisfy a generic
        # health check before the new child reports its bind failure.
        if (
            $health.status -eq "ok" -and
            $health.PSObject.Properties.Name -contains "domains" -and
            $health.PSObject.Properties.Name -contains "default_domain"
        ) {
            Start-Sleep -Milliseconds 200
            $process.Refresh()
            if (-not $process.HasExited) {
                $healthy = $true
                break
            }
        }
    } catch {
        Start-Sleep -Milliseconds 200
    }
}

if (-not $healthy) {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
    throw "Backend did not become healthy within $StartupTimeoutSeconds seconds."
}

[PSCustomObject]@{
    Pid = $process.Id
    Url = "http://${HostAddress}:$Port/"
    Status = $health.status
    CoreAgents = $health.core_agents
    SystemAgents = $health.system_agents
}
