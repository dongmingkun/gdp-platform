# Windows + Microsoft Word：更新报告目录并导出 PDF，Word 始终在后台运行。
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$reportPath = Join-Path $projectDir 'docs\out\课程设计报告.docx'
$pdfPath = Join-Path $projectDir 'docs\out\课程设计报告.pdf'
$wordApp = $null
$reportDoc = $null
try {
    $wordApp = New-Object -ComObject Word.Application
    $wordApp.Visible = $false
    $wordApp.DisplayAlerts = 0
    $wordApp.AutomationSecurity = 3
    $reportDoc = $wordApp.Documents.Open($reportPath)
    $reportDoc.Fields.Update() | Out-Null
    foreach ($toc in $reportDoc.TablesOfContents) { $toc.Update() }
    $reportDoc.Repaginate()
    $reportDoc.Save()
    $reportDoc.ExportAsFixedFormat($pdfPath, 17)
    Write-Output ('Rendered pages: ' + $reportDoc.ComputeStatistics(2))
    Write-Output $pdfPath
} finally {
    if ($null -ne $reportDoc) {
        $reportDoc.Close(0)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($reportDoc)
    }
    if ($null -ne $wordApp) {
        $wordApp.Quit()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($wordApp)
    }
}
