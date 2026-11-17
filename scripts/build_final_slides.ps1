param(
    [string]$InputPath = "docs/SLIDES_POINT_IN_TIME_FEATURE_STORE.md",
    [string]$OutputPath = "docs/SLIDES_POINT_IN_TIME_FEATURE_STORE.pdf"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$inputFile = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $InputPath))
$outputFile = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputPath))
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

if (-not (Test-Path -LiteralPath $inputFile)) { throw "Missing slide source: $inputFile" }
if (-not (Test-Path -LiteralPath $edge)) { throw "Microsoft Edge was not found: $edge" }

function Inline([string]$value) {
    $encoded = [System.Net.WebUtility]::HtmlEncode($value)
    $encoded = [regex]::Replace($encoded, '`([^`]+)`', '<code>$1</code>')
    $encoded = [regex]::Replace($encoded, '\*\*([^*]+)\*\*', '<strong>$1</strong>')
    return $encoded
}

$slides = ([System.IO.File]::ReadAllText($inputFile, [System.Text.Encoding]::UTF8) `
    -split '(?m)^---\s*$')
$rendered = [System.Text.StringBuilder]::new()

foreach ($slide in $slides) {
    if ([string]::IsNullOrWhiteSpace($slide)) { continue }
    [void]$rendered.AppendLine('<section class="slide">')
    $inCode = $false
    $inList = $false
    foreach ($line in ($slide -split "`r?`n")) {
        if ($line.Trim() -match '^```') {
            if ($inList) { [void]$rendered.AppendLine('</ul>'); $inList = $false }
            if ($inCode) { [void]$rendered.AppendLine('</code></pre>') }
            else { [void]$rendered.AppendLine('<pre><code>') }
            $inCode = -not $inCode
            continue
        }
        if ($inCode) {
            [void]$rendered.AppendLine([System.Net.WebUtility]::HtmlEncode($line))
            continue
        }
        if ($line -match '^(#{1,3})\s+(.+)$') {
            if ($inList) { [void]$rendered.AppendLine('</ul>'); $inList = $false }
            $level = $matches[1].Length
            [void]$rendered.AppendLine("<h$level>$(Inline $matches[2])</h$level>")
        } elseif ($line -match '^\s*-\s+(.+)$') {
            if (-not $inList) { [void]$rendered.AppendLine('<ul>'); $inList = $true }
            [void]$rendered.AppendLine("<li>$(Inline $matches[1])</li>")
        } elseif (-not [string]::IsNullOrWhiteSpace($line)) {
            if ($inList) { [void]$rendered.AppendLine('</ul>'); $inList = $false }
            [void]$rendered.AppendLine("<p>$(Inline $line.Trim())</p>")
        }
    }
    if ($inList) { [void]$rendered.AppendLine('</ul>') }
    if ($inCode) { [void]$rendered.AppendLine('</code></pre>') }
    [void]$rendered.AppendLine('</section>')
}

$html = @"
<!doctype html><html lang="vi"><head><meta charset="utf-8"><style>
@page { size: 13.333in 7.5in; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: #10233f; }
.slide { width: 13.333in; height: 7.5in; padding: .62in .78in; page-break-after: always;
  position: relative; overflow: hidden; background: linear-gradient(135deg,#fff 72%,#e9f4fb); }
.slide::after { content: "POINT-IN-TIME FEATURE STORE"; position: absolute; bottom: .22in;
  right: .55in; font-size: 9pt; letter-spacing: 1.2px; color: #4f7894; }
h1 { font-size: 34pt; margin: 1.65in 0 .35in; color: #123b66; text-align: center; }
h2 { font-size: 27pt; margin: 0 0 .35in; padding-bottom: .15in; color: #075b86;
  border-bottom: 3px solid #55a8c7; }
h3 { font-size: 20pt; color: #075b86; }
p, li { font-size: 18pt; line-height: 1.38; }
li { margin: .12in 0; }
pre { background: #10233f; color: #f5fbff; padding: .22in .28in; border-radius: 10px;
  font-size: 14pt; line-height: 1.35; overflow: hidden; }
code { font-family: Consolas, monospace; }
p code, li code { background: #e5f0f6; color: #004d73; padding: 1px 5px; border-radius: 4px; }
</style></head><body>$rendered</body></html>
"@

$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("pit-slides-" + [guid]::NewGuid())
[void](New-Item -ItemType Directory -Path $tempDir)
$htmlFile = Join-Path $tempDir "slides.html"
$tempPdf = Join-Path $tempDir "slides.pdf"
[System.IO.File]::WriteAllText($htmlFile, $html, [System.Text.Encoding]::UTF8)

try {
    & $edge --headless --disable-gpu --no-pdf-header-footer `
        --print-to-pdf="$tempPdf" ([System.Uri]$htmlFile).AbsoluteUri | Out-Null
    if (-not (Test-Path -LiteralPath $tempPdf)) { throw "PDF was not generated" }
    if (Test-Path -LiteralPath $outputFile) { [System.IO.File]::Delete($outputFile) }
    [System.IO.File]::Move($tempPdf, $outputFile)
    Write-Host "Generated: $outputFile"
} finally {
    if (Test-Path -LiteralPath $tempDir) {
        Get-ChildItem -LiteralPath $tempDir -Force -File -ErrorAction SilentlyContinue |
            ForEach-Object { $_.IsReadOnly = $false }
        [System.IO.Directory]::Delete($tempDir, $true)
    }
}
