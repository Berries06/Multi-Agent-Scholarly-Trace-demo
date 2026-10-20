param(
    [string]$InstanceName = 'Huawei_Phone',
    [string]$DeployRoot = 'C:\HarmonyOS-Emu',
    [string]$ImageRoot = 'D:\HarmonyOS-Sdk',
    [switch]$Status,
    [switch]$Stop,
    [int]$WaitSeconds = 240
)

$ErrorActionPreference = 'Stop'

# 研海寻踪 · 鸿蒙模拟器启动器
#
# 为什么不直接在 DevEco 里点「启动模拟器」：
# 模拟器启动前要用 RSA-PSS 校验镜像签名（image_signature/*.hwp7s）。镜像目录（imageRoot）
# 路径里只要有中文，模拟器读签名文件就失败，会报 00801019「镜像文件已被篡改」并强退；
# 镜像内容其实是好的（sha256 与签名里的摘要一致，见 docs/协作与运维/鸿蒙手机端.md）。
# DevEco 自己拉起的 imageRoot 是 %LOCALAPPDATA%\Huawei\Sdk，正好落在中文用户名下，所以必失败。
# 本脚本把 imageRoot 指到纯英文目录（默认 D:\HarmonyOS-Sdk），签名校验就能过。
# 设备起来后 DevEco 通过 hdc 一样能看见它（127.0.0.1:5555），Run / Debug 照常可用。
#
# 用法：
#   启动   powershell -ExecutionPolicy Bypass -File scripts\环境\启动鸿蒙模拟器.ps1
#   看状态 …… -Status
#   关掉   …… -Stop

function Invoke-Native {
    param([string]$FilePath, [string[]]$Arguments)
    $ErrorActionPreference = 'Continue'
    $out = & $FilePath @Arguments 2>&1
    return (@($out | ForEach-Object { "$_" }) -join "`n")
}

function Test-AsciiPath {
    param([string]$Path)
    foreach ($ch in $Path.ToCharArray()) {
        if ([int]$ch -gt 127) { return $false }
    }
    return $true
}

$devEco = 'C:\Program Files\Huawei\DevEco Studio'
$Emulator = Join-Path $devEco 'tools\emulator\Emulator.exe'
if (-not (Test-Path -LiteralPath $Emulator)) {
    throw '没找到 Emulator.exe。请确认这台电脑装了 DevEco Studio（默认在 C:\Program Files\Huawei\DevEco Studio）。'
}

$Hdc = Join-Path $devEco 'sdk\default\openharmony\toolchains\hdc.exe'
if (-not (Test-Path -LiteralPath $Hdc)) {
    $cmd = Get-Command hdc -ErrorAction SilentlyContinue
    if ($cmd) { $Hdc = $cmd.Source } else { $Hdc = $null }
}

function Get-Targets {
    if (-not $Hdc) { return @() }
    $raw = Invoke-Native $Hdc @('list targets')
    $lines = $raw -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -notmatch '^\[Empty\]$' }
    return @($lines)
}

function Get-DeviceParam {
    param([string]$Name)
    if (-not $Hdc) { return '' }
    return (Invoke-Native $Hdc @('shell', 'param', 'get', $Name)).Trim()
}

$instanceDir = Join-Path $DeployRoot $InstanceName

if ($Status) {
    Write-Host ('模拟器版本: ' + (Invoke-Native $Emulator @('-version')).Trim())
    Write-Host ('镜像目录  : ' + $ImageRoot)
    Write-Host ('实例目录  : ' + $instanceDir)
    $targets = Get-Targets
    if ($targets.Count -gt 0) {
        Write-Host ('设备状态  : 已连接 ' + ($targets -join ', '))
        Write-Host ('启动完成  : ' + (Get-DeviceParam 'bootevent.boot.completed'))
        Write-Host ('系统版本  : ' + (Get-DeviceParam 'const.product.software.version'))
    } else {
        Write-Host '设备状态  : 现在没有设备。不带参数运行本脚本可以启动一台。'
    }
    exit 0
}

if ($Stop) {
    Write-Host (Invoke-Native $Emulator @('-stop', $InstanceName))
    exit 0
}

$configFile = Join-Path $instanceDir 'config.ini'
$imageDir = Join-Path (Join-Path $ImageRoot 'system-image') 'HarmonyOS-5.1.1\phone_all_x86'

if (-not (Test-Path -LiteralPath $configFile)) {
    throw ('实例目录里没有 config.ini：' + $instanceDir + '。先在 DevEco 的 Device Manager 里建一台 Huawei_Phone，再把实例目录放到这里。')
}
if (-not (Test-Path -LiteralPath (Join-Path $imageDir 'system.img'))) {
    throw ('镜像不全：' + $imageDir + ' 里没有 system.img。请在 DevEco 的 Device Manager 里下载 Huawei_Phone 的镜像。')
}
if (-not (Test-AsciiPath $ImageRoot)) {
    throw ('镜像目录含非英文字符，模拟器会报 00801019 镜像校验失败：' + $ImageRoot + '。把镜像放到纯英文路径再运行。')
}
if (-not (Test-AsciiPath $DeployRoot)) {
    throw ('实例目录含非英文字符：' + $DeployRoot + '。换成纯英文路径再运行。')
}

$driveLetter = (Split-Path -Qualifier $DeployRoot).TrimEnd(':')
$freeGb = [math]::Round((Get-PSDrive -Name $driveLetter).Free / 1GB, 1)
if ($freeGb -lt 12) {
    throw ('实例所在盘只剩 ' + $freeGb + ' GB。模拟器要 12 GB 以上才肯启动（否则报 00801002），先清理磁盘。')
}

$running = @(Get-Process -Name 'Emulator' -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
    Write-Host '已经有一台模拟器在运行，直接复用它。'
} else {
    Write-Host '=== 启动鸿蒙模拟器 ==='
    Write-Host ('镜像目录: ' + $ImageRoot)
    Write-Host ('实例目录: ' + $instanceDir)
    Write-Host ('可用空间: ' + $freeGb + ' GB')
    $startArgs = @('-hvd', $InstanceName, '-path', $DeployRoot, '-imageRoot', $ImageRoot)
    Start-Process -FilePath $Emulator -ArgumentList $startArgs | Out-Null
}

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$target = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $targets = Get-Targets
    if ($targets.Count -gt 0) { $target = $targets[0]; break }
    if (@(Get-Process -Name 'Emulator' -ErrorAction SilentlyContinue).Count -eq 0) { break }
}

if (-not $target) {
    Write-Host ''
    Write-Host ('没等到设备。看一眼 ' + (Join-Path $instanceDir 'Emulator.log') + ' 的最后几行。')
    exit 1
}

Write-Host ('设备已连上: ' + $target)
$booted = $false
while ((Get-Date) -lt $deadline) {
    if ((Get-DeviceParam 'bootevent.boot.completed') -eq 'true') { $booted = $true; break }
    Start-Sleep -Seconds 3
}

if ($booted) {
    Write-Host ('系统已启动完成: ' + (Get-DeviceParam 'const.product.software.version'))
    Write-Host ''
    Write-Host '在 DevEco 里 Run / Debug 时，设备选 127.0.0.1:5555 这一项。'
    Write-Host '关掉模拟器：运行「停止鸿蒙模拟器.bat」，或本脚本加 -Stop。'
} else {
    Write-Host '设备连上了，但还没跑到启动完成。再等一会儿，或者看 Emulator.log。'
    exit 1
}
