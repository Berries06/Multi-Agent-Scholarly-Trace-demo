param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 5000
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
$stateRoot = Join-Path $projectRoot ".mlflow"
$pidPath = Join-Path $stateRoot "server.pid"
$launcherPidPath = Join-Path $stateRoot "launcher.pid"
if (-not (Test-Path -LiteralPath $pidPath) -and -not (Test-Path -LiteralPath $launcherPidPath)) {
    Write-Host "No project MLflow PID file was found."
    exit 0
}

$activeListenerPid = Get-ListeningProcessId $Port
$launcherPid = $null
if (Test-Path -LiteralPath $launcherPidPath) {
    $launcherPid = [int](Get-Content -LiteralPath $launcherPidPath -Encoding ASCII)
    $launcher = Get-Process -Id $launcherPid -ErrorAction SilentlyContinue
    if ($launcher) {
        Stop-Process -Id $launcherPid
        Write-Host "Stopped project MLflow launcher $launcherPid."
    }
}

if (Test-Path -LiteralPath $pidPath) {
    $serverPid = [int](Get-Content -LiteralPath $pidPath -Encoding ASCII)
} else {
    $serverPid = $null
}

$serverPids = @($serverPid, $activeListenerPid) |
    Where-Object { $null -ne $_ -and $_ -ne $launcherPid } |
    Select-Object -Unique
foreach ($currentServerPid in $serverPids) {
    $server = Get-Process -Id $currentServerPid -ErrorAction SilentlyContinue
    if (-not $server) {
        continue
    }
    Stop-Process -Id $currentServerPid
    Write-Host "Stopped project MLflow server $currentServerPid."
}
Remove-Item -LiteralPath $launcherPidPath -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
