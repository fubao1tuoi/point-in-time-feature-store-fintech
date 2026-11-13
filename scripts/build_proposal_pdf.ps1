param(
    [string]$InputPath = "docs/DE_CUONG_DE_TAI_PIT_FEATURE_STORE.md",
    [string]$OutputPath = "docs/POINT_IN_TIME_CORRECT_FEATURE_STORE.pdf"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$inputFile = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $InputPath))
$outputFile = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputPath))
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

if (-not (Test-Path -LiteralPath $inputFile)) {
    throw "Missing Markdown source: $inputFile"
}
if (-not (Test-Path -LiteralPath $edge)) {
    throw "Microsoft Edge was not found: $edge"
}

function Convert-InlineMarkdown([string]$text) {
    $encoded = [System.Net.WebUtility]::HtmlEncode($text)
    $encoded = [regex]::Replace($encoded, '```([^`]+)```', '<code>$1</code>')
    $encoded = [regex]::Replace($encoded, '`([^`]+)`', '<code>$1</code>')
    $encoded = [regex]::Replace($encoded, '\*\*([^*]+)\*\*', '<strong>$1</strong>')
    $encoded = [regex]::Replace(
        $encoded,
        '\[([^\]]+)\]\((https?://[^)]+)\)',
        '<a href="$2">$1</a>'
    )
    $encoded = [regex]::Replace(
        $encoded,
        '&lt;(https?://[^&]+)&gt;',
        '<a href="$1">$1</a>'
    )
    return $encoded
}

$lines = [System.IO.File]::ReadAllLines($inputFile, [System.Text.Encoding]::UTF8)
$body = [System.Text.StringBuilder]::new()
$inCode = $false
$inUnorderedList = $false
$inOrderedList = $false
$paragraph = [System.Collections.Generic.List[string]]::new()

function Close-Paragraph {
    if ($paragraph.Count -gt 0) {
        $renderedLines = [System.Collections.Generic.List[string]]::new()
        foreach ($paragraphLine in $paragraph) {
            $hasHardBreak = $paragraphLine.EndsWith("  ") -or $paragraphLine.EndsWith("\")
            $lineContent = if ($paragraphLine.EndsWith("\")) {
                $paragraphLine.Substring(0, $paragraphLine.Length - 1).TrimEnd()
            } else {
                $paragraphLine.TrimEnd()
            }
            $rendered = Convert-InlineMarkdown $lineContent
            if ($hasHardBreak) {
                $renderedLines.Add("$rendered<br>")
            } else {
                $renderedLines.Add($rendered)
            }
        }
        [void]$body.AppendLine("<p>$(($renderedLines -join ' ').Trim())</p>")
        $paragraph.Clear()
    }
}

function Close-Lists {
    if ($script:inUnorderedList) {
        [void]$body.AppendLine("</ul>")
        $script:inUnorderedList = $false
    }
    if ($script:inOrderedList) {
        [void]$body.AppendLine("</ol>")
        $script:inOrderedList = $false
    }
}

for ($index = 0; $index -lt $lines.Count; $index++) {
    $line = $lines[$index]

    if ($line.Trim() -match '^```(?:[A-Za-z0-9_+.-]+)?\s*$') {
        Close-Paragraph
        Close-Lists
        if ($inCode) {
            [void]$body.AppendLine('</code></pre>')
            $inCode = $false
        } else {
            [void]$body.AppendLine('<pre><code>')
            $inCode = $true
        }
        continue
    }
    if ($inCode) {
        [void]$body.AppendLine([System.Net.WebUtility]::HtmlEncode($line))
        continue
    }
    if ([string]::IsNullOrWhiteSpace($line)) {
        Close-Paragraph
        Close-Lists
        continue
    }
    if ($line -match '^---+$') {
        Close-Paragraph
        Close-Lists
        [void]$body.AppendLine('<hr>')
        continue
    }
    if ($line -match '^(#{1,6})\s+(.+)$') {
        Close-Paragraph
        Close-Lists
        $level = $matches[1].Length
        [void]$body.AppendLine("<h$level>$(Convert-InlineMarkdown $matches[2])</h$level>")
        continue
    }
    if (
        $line.TrimStart().StartsWith('|') -and
        $index + 1 -lt $lines.Count -and
        $lines[$index + 1] -match '^\s*\|?[\s:|-]+\|\s*$'
    ) {
        Close-Paragraph
        Close-Lists
        $headers = $line.Trim().Trim('|').Split('|')
        [void]$body.AppendLine('<table><thead><tr>')
        foreach ($header in $headers) {
            [void]$body.AppendLine("<th>$(Convert-InlineMarkdown $header.Trim())</th>")
        }
        [void]$body.AppendLine('</tr></thead><tbody>')
        $index += 2
        while ($index -lt $lines.Count -and $lines[$index].TrimStart().StartsWith('|')) {
            $cells = $lines[$index].Trim().Trim('|').Split('|')
            [void]$body.AppendLine('<tr>')
            foreach ($cell in $cells) {
                [void]$body.AppendLine("<td>$(Convert-InlineMarkdown $cell.Trim())</td>")
            }
            [void]$body.AppendLine('</tr>')
            $index++
        }
        [void]$body.AppendLine('</tbody></table>')
        $index--
        continue
    }
    if ($line -match '^\s*-\s+(.+)$') {
        Close-Paragraph
        if ($inOrderedList) { Close-Lists }
        if (-not $inUnorderedList) {
            [void]$body.AppendLine('<ul>')
            $inUnorderedList = $true
        }
        [void]$body.AppendLine("<li>$(Convert-InlineMarkdown $matches[1])</li>")
        continue
    }
    if ($line -match '^\s*\d+\.\s+(.+)$') {
        Close-Paragraph
        if ($inUnorderedList) { Close-Lists }
        if (-not $inOrderedList) {
            [void]$body.AppendLine('<ol>')
            $inOrderedList = $true
        }
        [void]$body.AppendLine("<li>$(Convert-InlineMarkdown $matches[1])</li>")
        continue
    }
    if ($line -match '^>\s*(.+)$') {
        Close-Paragraph
        Close-Lists
        [void]$body.AppendLine("<blockquote>$(Convert-InlineMarkdown $matches[1])</blockquote>")
        continue
    }
    $paragraph.Add($line.TrimStart())
}

Close-Paragraph
Close-Lists
if ($inCode) { [void]$body.AppendLine('</code></pre>') }

$css = @'
@page { size: A4; margin: 18mm 17mm 18mm 19mm; }
* { box-sizing: border-box; }
body { font-family: Arial, sans-serif; color: #172033; font-size: 10.5pt; line-height: 1.48; margin: 0; }
h1 { color: #123a63; font-size: 22pt; text-align: center; margin: 18mm 0 8mm; line-height: 1.25; }
h2 { color: #0d5277; font-size: 15pt; margin: 8mm 0 3mm; border-bottom: 1px solid #b9d2df; padding-bottom: 1.5mm; break-after: avoid; }
h3 { color: #176b87; font-size: 12pt; margin: 5mm 0 2mm; break-after: avoid; }
p { margin: 0 0 3mm; text-align: justify; }
ul, ol { margin: 1mm 0 3mm 7mm; padding-left: 5mm; }
li { margin: 0 0 1.2mm; }
table { border-collapse: collapse; width: 100%; margin: 3mm 0 5mm; font-size: 9.2pt; break-inside: avoid; }
th { background: #155b7c; color: white; text-align: left; }
th, td { border: 1px solid #91afbd; padding: 2mm; vertical-align: top; }
tr:nth-child(even) td { background: #f2f7f9; }
pre { background: #f3f5f7; border-left: 4px solid #1f7894; padding: 3mm; overflow-wrap: anywhere; white-space: pre-wrap; break-inside: avoid; }
code { font-family: Consolas, monospace; color: #8b2742; font-size: 9pt; }
a { color: #075d8c; text-decoration: none; }
hr { border: 0; border-top: 2px solid #155b7c; margin: 6mm 0; }
blockquote { background: #eef6f9; border-left: 4px solid #1f7894; margin: 3mm 0; padding: 3mm; }
h1 + h2 { page-break-before: auto; }
'@

$html = @"
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>Point-in-Time Correct Feature Store</title>
<style>$css</style>
</head>
<body>
$body
</body>
</html>
"@

$tempHtml = Join-Path ([System.IO.Path]::GetTempPath()) "pit-feature-store-proposal.html"
$tempPdf = Join-Path ([System.IO.Path]::GetTempPath()) "pit-feature-store-proposal-$([guid]::NewGuid()).pdf"
[System.IO.File]::WriteAllText($tempHtml, $html, [System.Text.UTF8Encoding]::new($false))
[System.IO.Directory]::CreateDirectory((Split-Path -Parent $outputFile)) | Out-Null

$fileUrl = ([System.Uri]$tempHtml).AbsoluteUri
& $edge --headless --disable-gpu --no-pdf-header-footer "--print-to-pdf=$tempPdf" $fileUrl | Out-Null

if (-not (Test-Path -LiteralPath $tempPdf)) {
    throw "PDF generation failed before writing output: $outputFile"
}
Move-Item -LiteralPath $tempPdf -Destination $outputFile -Force
Write-Output "Generated: $outputFile"
