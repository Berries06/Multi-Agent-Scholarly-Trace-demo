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
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Python Launcher 未提供 3.12，继续检查其他可用运行环境。" -ForegroundColor Yellow
        }
    }

    if (-not (Test-Path -LiteralPath $Python)) {
        $PythonCandidates = @(
            (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")
        )
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($PythonCommand) { $PythonCandidates += $PythonCommand.Source }

        $BasePython = $null
        foreach ($Candidate in ($PythonCandidates | Select-Object -Unique)) {
            if (-not (Test-Path -LiteralPath $Candidate)) { continue }
            $Version = & $Candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            if ($LASTEXITCODE -eq 0 -and [version]$Version.Trim() -ge [version]"3.12") {
                $BasePython = $Candidate
                break
            }
        }
        if (-not $BasePython) { throw "未找到 Python 3.12 或更高版本。" }
        Write-Host "使用 Python $Version：$BasePython" -ForegroundColor Cyan
        & $BasePython -m venv $VenvRoot
    }
    if ($LASTEXITCODE -ne 0) { throw "创建 .venv 失败。" }
}

& $Python -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "升级 Python 打包工具失败。" }

$Extras = "desktop,test,labs,package,submission"
if ($IncludeResearchTools) { $Extras += ",documents,tracking" }
# 打包工具已在当前 .venv 中准备完成；关闭构建隔离可避免 pip 再次
# 创建临时环境并重复下载 setuptools，提升弱网/受限网络下的成功率。
& $Python -m pip install --no-build-isolation -e "$ProjectRoot[$Extras]"
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
