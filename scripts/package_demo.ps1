param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$distDirectory = Join-Path $projectRoot "dist"
if (-not $OutputPath) {
    $OutputPath = Join-Path $distDirectory "yanhai-demo-windows.zip"
}
$stagingDirectory = Join-Path $distDirectory ".yanhai-package-staging"

New-Item -ItemType Directory -Path $distDirectory -Force | Out-Null
if (Test-Path -LiteralPath $stagingDirectory) {
    throw "Staging directory already exists: $stagingDirectory. Check for another packaging task."
}
New-Item -ItemType Directory -Path $stagingDirectory | Out-Null

$items = @(
    "README.md",
    "RUN_DEMO.bat",
    "STOP_DEMO.bat",
    "OPEN_DEMO.url",
    "GITHUB_REPOSITORY.url",
    "pyproject.toml",
    "EXPERIMENT_AUDIT.md",
    "EXPERIMENT_AUDIT.json",
    "Dockerfile",
    "docker-compose.yml",
    "config",
    "data",
    "deploy",
    "docs",
    "scripts",
    "src",
    "submission_materials",
    "tests",
    "web"
)

try {
    foreach ($item in $items) {
        $source = Join-Path $projectRoot $item
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Required package path does not exist: $source"
        }
        Copy-Item -LiteralPath $source -Destination $stagingDirectory -Recurse
    }

    $resolvedStagingDirectory = (Resolve-Path -LiteralPath $stagingDirectory).Path
    $stagingPrefix = $resolvedStagingDirectory.TrimEnd('\') + '\'
    $generatedCaches = @(
        Get-ChildItem -LiteralPath $resolvedStagingDirectory -Directory -Recurse -Force |
            Where-Object { $_.Name -eq "__pycache__" }
    )
    foreach ($cacheDirectory in $generatedCaches) {
        $resolvedCacheDirectory = (Resolve-Path -LiteralPath $cacheDirectory.FullName).Path
        if (-not $resolvedCacheDirectory.StartsWith($stagingPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a generated cache outside staging: $resolvedCacheDirectory"
        }
        Remove-Item -LiteralPath $resolvedCacheDirectory -Recurse -Force
    }

    Compress-Archive `
        -Path (Join-Path $stagingDirectory "*") `
        -DestinationPath $OutputPath `
        -CompressionLevel Optimal `
        -Force
} finally {
    if (Test-Path -LiteralPath $stagingDirectory) {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force
    }
}

$archive = Get-Item -LiteralPath $OutputPath
[PSCustomObject]@{
    Path = $archive.FullName
    SizeMB = [math]::Round($archive.Length / 1MB, 2)
    IncludesGitHistory = $false
    IncludesRuntimeOutputs = $false
}
