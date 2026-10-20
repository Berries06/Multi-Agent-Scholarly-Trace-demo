param([switch]$SkipBuild)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到 .venv；请先运行 scripts/环境/创建统一环境.ps1。"
}

Push-Location $ProjectRoot
try {
    & $Python -m compileall -q src scripts
    if ($LASTEXITCODE -ne 0) { throw "Python 编译检查失败。" }
    & $Python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Python 测试失败。" }

    # 覆盖率门槛写在 pyproject.toml（fail_under = 75）。以前这条线只是写在配置里、
    # 没有任何命令执行它，2026-10-16 接进来：跑不到门槛就让这次检查不过。
    & $Python -m coverage run --branch --source=yanhai -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw "覆盖率统计时的测试执行失败。" }
    & $Python -m coverage report
    if ($LASTEXITCODE -ne 0) { throw "覆盖率没有达到 pyproject.toml 里写的门槛。" }

    Push-Location "frontend"
    try {
        cmd /c npm run typecheck
        if ($LASTEXITCODE -ne 0) { throw "前端类型检查失败。" }
        if (-not $SkipBuild) {
            cmd /c npm run build
            if ($LASTEXITCODE -ne 0) { throw "前端构建失败。" }
        }
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}

Write-Host "全部检查通过。" -ForegroundColor Green
