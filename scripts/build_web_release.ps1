param(
    [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReleaseRoot = Join-Path $ProjectRoot "release"
$Archive = Join-Path $ReleaseRoot "yanhai-web-$Version.tar.gz"

New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
if (Test-Path -LiteralPath $Archive) {
    Remove-Item -LiteralPath $Archive -Force
}

Push-Location $ProjectRoot
try {
    tar.exe -czf $Archive `
        --exclude="src/yanhai_trace.egg-info" `
        --exclude="*/__pycache__" `
        --exclude="*.pyc" `
        src data web pyproject.toml README.md
    if ($LASTEXITCODE -ne 0) {
        throw "Web release build failed."
    }
}
finally {
    Pop-Location
}

$Hash = Get-FileHash -LiteralPath $Archive -Algorithm SHA256
Write-Host "Web release package: $Archive"
Write-Host "SHA-256: $($Hash.Hash.ToLowerInvariant())"
