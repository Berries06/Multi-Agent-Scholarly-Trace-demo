param(
    [switch]$Recreate,
    [switch]$IncludeResearchTools,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvRoot = Join-Path $ProjectRoot ".venv"
$Python = Join-Path $VenvRoot "Scripts\python.exe"

if ($Recreate -and (Test-Path -LiteralPath $VenvRoot)) {
    $ResolvedVenv = (Resolve-Path -LiteralPath $VenvRoot).Path
    $ExpectedVenv = Join-Path $ProjectRoot ".venv"
    if (-not $ResolvedVenv.Equals($ExpectedVenv, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝删除预期目录之外的环境：$ResolvedVenv"
    }
    Remove-Item -LiteralPath $ResolvedVenv -Recurse -Force
}

if (-not (Test-Path -LiteralPath $Python)) {
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        & $Launcher.Source -3.12 -m venv $VenvRoot
    } else {
        $BasePython = Get-Command python -ErrorAction SilentlyContinue
        if (-not $BasePython) { throw "未找到 CPython 3.12。" }
        $Version = & $BasePython.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        if ($Version.Trim() -ne "3.12") { throw "需要 CPython 3.12，当前为 $Version。" }
        & $BasePython.Source -m venv $VenvRoot
    }
    if ($LASTEXITCODE -ne 0) { throw "创建 .venv 失败。" }
}

& $Python -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "升级 Python 打包工具失败。" }

$Extras = "desktop,test,labs,package,submission"
if ($IncludeResearchTools) { $Extras += ",documents,tracking" }
& $Python -m pip install -e "$ProjectRoot[$Extras]"
if ($LASTEXITCODE -ne 0) { throw "安装项目依赖失败。" }

if (-not $SkipFrontend) {
    Push-Location (Join-Path $ProjectRoot "frontend")
    try {
        cmd /c npm ci
        if ($LASTEXITCODE -ne 0) { throw "安装前端依赖失败。" }
    } finally {
        Pop-Location
    }
}

Write-Host "统一环境已就绪：$VenvRoot" -ForegroundColor Green
Write-Host "Python：$Python"
Write-Host "研究工具：$($IncludeResearchTools.IsPresent)"
