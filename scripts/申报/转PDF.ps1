# 把作品方案（docx）与答辩 PPT（pptx）导出成 PDF。
#
# 为什么用 Office：这台机器上没有 LibreOffice / pandoc，但装了 Office。
# Word 导出时顺手把目录域更新一遍，页码才是真的；PowerPoint 导出能保证中文字体与版面不走样。
# 导出 PPT 时同时把每页导成 PNG，方便逐页核对版面。
#
# 用法（仓库根目录），两个参数都可省略：
#   pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/申报/转PDF.ps1
#   pwsh -NoProfile -File scripts/申报/转PDF.ps1 -Docx docs/申报材料/x.docx
#
# 注意：Office 自动化在交互会话里可能弹窗卡住，所以这里丢进后台作业跑并设超时。

param(
    [string]$Docx = "docs/申报材料/2026AIC_作品方案.docx",
    [string]$Pptx = "docs/申报材料/2026AIC_答辩PPT.pptx",
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$root = (Get-Location).Path
$docxPath = Join-Path $root $Docx
$pptxPath = Join-Path $root $Pptx
$pngDir = Join-Path $root ".tmp/申报/幻灯片"

$job = Start-Job -ArgumentList $docxPath, $pptxPath, $pngDir -ScriptBlock {
    param($docx, $pptx, $pngDir)
    $ErrorActionPreference = "Stop"

    if (Test-Path $docx) {
        $word = New-Object -ComObject Word.Application
        try {
            $word.Visible = $false
            $word.DisplayAlerts = 0
            $doc = $word.Documents.Open($docx, $false, $false)
            try {
                foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
                $doc.Fields.Update() | Out-Null
                $doc.Repaginate()
                $pages = $doc.ComputeStatistics(2)
                $chars = $doc.ComputeStatistics(3)
                $target = [System.IO.Path]::ChangeExtension($docx, ".pdf")
                $doc.ExportAsFixedFormat($target, 17)
                Write-Output ("WORD pages={0} chars={1}" -f $pages, $chars)
                Write-Output ("WORD pdf=" + $target)
            } finally { $doc.Close(0) }
        } finally {
            $word.Quit()
            [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
        }
    } else {
        Write-Output "WORD 跳过：找不到 $docx"
    }

    if (Test-Path $pptx) {
        $ppt = New-Object -ComObject PowerPoint.Application
        try {
            $presentation = $ppt.Presentations.Open($pptx, $true, $false, $false)
            try {
                $slides = $presentation.Slides.Count
                $target = [System.IO.Path]::ChangeExtension($pptx, ".pdf")
                $presentation.SaveAs($target, 32)
                New-Item -ItemType Directory -Force -Path $pngDir | Out-Null
                foreach ($slide in $presentation.Slides) {
                    $file = Join-Path $pngDir ("slide{0:D2}.png" -f $slide.SlideIndex)
                    $slide.Export($file, "PNG", 1600, 900)
                }
                Write-Output ("PPT slides={0}" -f $slides)
                Write-Output ("PPT pdf=" + $target)
            } finally { $presentation.Close() }
        } finally {
            $ppt.Quit()
            [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
        }
    } else {
        Write-Output "PPT 跳过：找不到 $pptx"
    }
}

$finished = Wait-Job $job -Timeout $TimeoutSeconds
if ($finished) {
    Receive-Job $job
} else {
    Write-Output ("超时（{0}s），已终止 Office 进程。" -f $TimeoutSeconds)
    Stop-Job $job
    Get-Process WINWORD, POWERPNT -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
Remove-Job $job -Force -ErrorAction SilentlyContinue

Get-ChildItem "docs/申报材料" -Filter "2026AIC*.pdf" -ErrorAction SilentlyContinue |
    ForEach-Object { "{0}  {1:N2} MB" -f $_.Name, ($_.Length / 1MB) }
