param(
    [string]$Version = "0.1.0",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$DistRoot = Join-Path $ReleaseRoot "qt-dist"
$WorkRoot = Join-Path $ProjectRoot "tmp\pyinstaller"
$SpecRoot = Join-Path $ProjectRoot "tmp\pyinstaller-spec"
$Archive = Join-Path $ReleaseRoot "YanhaiTrace-Windows-x64-$Version.zip"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python not found at $Python. Create the project virtual environment first."
}

& $Python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Run: .venv\Scripts\python.exe -m pip install PyInstaller"
}

if (-not $SkipTests) {
    & $Python -m unittest discover -s (Join-Path $ProjectRoot "tests") -v
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed; stopping the build."
    }
}

New-Item -ItemType Directory -Force -Path $ReleaseRoot, $DistRoot, $WorkRoot, $SpecRoot | Out-Null

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name "YanhaiTrace" `
    --paths (Join-Path $ProjectRoot "src") `
    --add-data "$ProjectRoot\data;data" `
    --distpath $DistRoot `
    --workpath $WorkRoot `
    --specpath $SpecRoot `
    (Join-Path $ProjectRoot "scripts\qt_entry.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$AppDirectory = Join-Path $DistRoot "YanhaiTrace"
Copy-Item `
    -LiteralPath (Join-Path $ProjectRoot "packaging\WINDOWS_README.txt") `
    -Destination (Join-Path $AppDirectory "README.txt") `
    -Force

if (Test-Path -LiteralPath $Archive) {
    Remove-Item -LiteralPath $Archive -Force
}
tar.exe -a -cf $Archive -C $DistRoot "YanhaiTrace"
if ($LASTEXITCODE -ne 0) {
    throw "ZIP archive creation failed."
}

$Hash = Get-FileHash -LiteralPath $Archive -Algorithm SHA256
Write-Host "Qt validation package: $Archive"
Write-Host "SHA-256: $($Hash.Hash.ToLowerInvariant())"
Write-Host "Size: $([math]::Round((Get-Item -LiteralPath $Archive).Length / 1MB, 2)) MiB"
