param([string]$Version = "", [switch]$SkipTests)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$DistRoot = Join-Path $ReleaseRoot "桌面端"
$WorkRoot = Join-Path $ProjectRoot "tmp\pyinstaller"
$SpecRoot = Join-Path $ProjectRoot "tmp\pyinstaller-spec"


if (-not (Test-Path -LiteralPath $Python)) { throw "未找到统一环境 .venv。" }
if (-not $Version) { $Version = (& $Python -c "from importlib.metadata import version; print(version('yanhai-trace'))").Trim() }
$Archive = Join-Path $ReleaseRoot "研海寻踪桌面端-Windows-x64-$Version.zip"
& $Python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) { throw "统一环境中未安装 PyInstaller。" }
if (-not $SkipTests) {
    & $Python -m unittest tests.test_product_client -v
    if ($LASTEXITCODE -ne 0) { throw "桌面 API 客户端测试失败。" }
}

New-Item -ItemType Directory -Force -Path $ReleaseRoot, $DistRoot, $WorkRoot, $SpecRoot | Out-Null
& $Python -m PyInstaller `
    --noconfirm --clean --onedir --windowed `
    --name "研海寻踪" `
    --paths (Join-Path $ProjectRoot "src") `
    --distpath $DistRoot `
    --workpath $WorkRoot `
    --specpath $SpecRoot `
    (Join-Path $ProjectRoot "scripts\桌面端入口.py")
if ($LASTEXITCODE -ne 0) { throw "桌面端构建失败。" }

if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
tar.exe -a -cf $Archive -C $DistRoot "研海寻踪"
if ($LASTEXITCODE -ne 0) { throw "桌面端压缩包创建失败。" }
$Hash = Get-FileHash -LiteralPath $Archive -Algorithm SHA256
Write-Host "桌面端发布包：$Archive"
Write-Host "SHA-256：$($Hash.Hash.ToLowerInvariant())"
