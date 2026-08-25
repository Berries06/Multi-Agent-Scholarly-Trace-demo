param([string]$Version = "")

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "未找到统一环境 .venv。" }
if (-not $Version) { $Version = (& $Python -c "from importlib.metadata import version; print(version('yanhai-trace'))").Trim() }
$ReleaseRoot = Join-Path $ProjectRoot "release"
$Archive = Join-Path $ReleaseRoot "yanhai-product-$Version.tar.gz"

Push-Location (Join-Path $ProjectRoot "frontend")
try {
    cmd /c npm ci
    if ($LASTEXITCODE -ne 0) { throw "前端依赖安装失败。" }
    cmd /c npm run build
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败。" }
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }

Push-Location $ProjectRoot
try {
    tar.exe -czf $Archive `
        --exclude="*/__pycache__" `
        --exclude="*.pyc" `
        --exclude="frontend/node_modules" `
        --exclude="outputs/*" `
        --exclude="secret/*" `
        src data config frontend/dist scripts deploy tests/experiments pyproject.toml README.md Dockerfile docker-compose.yml
    if ($LASTEXITCODE -ne 0) { throw "产品发布包构建失败。" }
} finally {
    Pop-Location
}

$Hash = Get-FileHash -LiteralPath $Archive -Algorithm SHA256
Write-Host "产品发布包: $Archive"
Write-Host "SHA-256: $($Hash.Hash.ToLowerInvariant())"
