param(
    [string]$OutputPath = "docs/GCP_CLOUD_PIPELINE_ARCHITECTURE.pdf"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputFile = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputPath))
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

if (-not (Test-Path -LiteralPath $edge)) {
    throw "Microsoft Edge was not found: $edge"
}

$html = @'
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>GCP Pipeline Architecture</title>
<style>
@page { size: A4 landscape; margin: 8mm; }
* { box-sizing: border-box; }
body {
  margin: 0;
  color: #10233f;
  background: #ffffff;
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: 12px;
}
.page {
  width: 100%;
  min-height: 188mm;
  page-break-after: always;
  position: relative;
  padding: 2mm 3mm;
}
.page:last-child { page-break-after: auto; }
h1 {
  margin: 0 0 2mm;
  color: #123b63;
  font-size: 25px;
  letter-spacing: .2px;
}
.subtitle {
  margin-bottom: 4mm;
  color: #53677e;
  font-size: 12px;
}
.band {
  border: 1.5px solid #c6d6e5;
  border-radius: 12px;
  padding: 3mm;
  background: #f8fbfe;
  box-shadow: 0 2px 7px rgba(30, 65, 95, .08);
}
.band-title {
  margin: 0 0 2mm;
  color: #2f5375;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .5px;
}
.row { display: flex; align-items: stretch; gap: 2.5mm; }
.row.center { align-items: center; justify-content: center; }
.box {
  min-width: 0;
  min-height: 19mm;
  border-radius: 9px;
  padding: 3mm;
  text-align: center;
  display: flex;
  flex-direction: column;
  justify-content: center;
  border: 1.3px solid #91abc2;
  background: #ffffff;
  flex: 1;
  overflow-wrap: anywhere;
}
.box strong { font-size: 13px; margin-bottom: 1mm; }
.box small { color: #52667a; line-height: 1.35; }
.blue { background: #e8f3fc; border-color: #4692c6; }
.green { background: #e9f7ef; border-color: #4f9a6d; }
.orange { background: #fff2df; border-color: #d9973f; }
.purple { background: #f1ecfb; border-color: #8b70bd; }
.gray { background: #f0f3f6; border-color: #8c9baa; }
.arrow {
  align-self: center;
  color: #2d678f;
  font-size: 24px;
  font-weight: 700;
  flex: 0 0 auto;
}
.down {
  height: 8mm;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #2d678f;
  font-size: 25px;
  line-height: 1;
}
.top-grid {
  display: grid;
  grid-template-columns: 1.05fr .75fr;
  gap: 4mm;
}
.pipeline { margin-top: 3mm; }
.storage-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2mm;
}
.storage-grid .box { min-height: 18mm; padding: 2mm 1.5mm; }
.storage-grid strong { font-size: 11px; }
.storage-grid small { font-size: 9px; }
.observability {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 3mm;
  margin-top: 3mm;
}
.legend {
  display: flex;
  gap: 4mm;
  justify-content: flex-end;
  margin-top: 2mm;
  color: #5d6f81;
  font-size: 10px;
}
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 1mm; }
.sequence {
  display: grid;
  grid-template-columns: 38mm 9mm 1fr;
  gap: 1.8mm;
  align-items: stretch;
  margin-top: 3mm;
}
.seq-step {
  border-radius: 9px;
  padding: 2.5mm 3mm;
  border: 1.2px solid #9db4c8;
  background: #f8fbfe;
  min-height: 18mm;
}
.seq-step strong { display: block; margin-bottom: 1mm; font-size: 12px; }
.seq-time {
  border-radius: 8px;
  background: #123b63;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}
.seq-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #2d678f;
  font-size: 24px;
  font-weight: 700;
}
.second-grid {
  display: grid;
  grid-template-columns: 1.35fr .85fr;
  gap: 5mm;
}
.status-card {
  padding: 3mm;
  border-radius: 10px;
  border: 1.3px solid #a8bdcf;
  margin-bottom: 3mm;
}
.status-card h2 { margin: 0 0 2mm; font-size: 15px; }
.done { background: #eaf7ef; border-color: #55a071; }
.todo { background: #fff4e3; border-color: #d69a4b; }
ul { margin: 0; padding-left: 5mm; line-height: 1.5; }
.note {
  margin-top: 3mm;
  padding: 3mm;
  border-left: 5px solid #4b89b3;
  background: #edf6fc;
  line-height: 1.45;
}
.footer {
  position: absolute;
  right: 3mm;
  bottom: 0;
  color: #76889a;
  font-size: 9px;
}
</style>
</head>
<body>

<section class="page">
  <h1>Kiến trúc Point-in-Time Feature Store trên Google Cloud</h1>
  <div class="subtitle">Batch pipeline: được kích hoạt theo lịch, xử lý đến khi hoàn thành rồi dừng — không có compute chạy liên tục.</div>

  <div class="top-grid">
    <div class="band">
      <div class="band-title">1. Đóng gói và phát hành code</div>
      <div class="row center">
        <div class="box gray"><strong>GitHub</strong><small>Source code và configuration</small></div>
        <div class="arrow">→</div>
        <div class="box blue"><strong>Cloud Build</strong><small>Build image<br>PIT demo<br>Non-root check</small></div>
        <div class="arrow">→</div>
        <div class="box purple"><strong>Artifact Registry</strong><small>Docker image có version và digest</small></div>
      </div>
    </div>

    <div class="band">
      <div class="band-title">2. Kích hoạt và điều phối</div>
      <div class="row center">
        <div class="box orange"><strong>Cloud Scheduler</strong><small>Kích hoạt hằng ngày</small></div>
        <div class="arrow">→</div>
        <div class="box blue"><strong>Google Workflows</strong><small>Thứ tự, retry và failure path</small></div>
      </div>
    </div>
  </div>

  <div class="down">↓</div>

  <div class="band pipeline">
    <div class="band-title">3. Cloud Run Jobs — cùng một image, mỗi job gọi một command riêng</div>
    <div class="row center">
      <div class="box blue"><strong>pit-ingest</strong><small>Bronze ingestion<br>Thêm ingest metadata</small></div>
      <div class="arrow">→</div>
      <div class="box blue"><strong>pit-silver</strong><small>Cast, deduplicate, join identity<br>Tạo event time và entity IDs</small></div>
      <div class="arrow">→</div>
      <div class="box blue"><strong>pit-features</strong><small>Tính historical features<br>Strict PIT cutoff</small></div>
      <div class="arrow">→</div>
      <div class="box blue"><strong>pit-score</strong><small>Dự báo fraud cho batch mới</small></div>
    </div>
  </div>

  <div class="down">↓</div>

  <div class="band">
    <div class="band-title">4. Cloud Storage — các lớp dữ liệu có version</div>
    <div class="storage-grid">
      <div class="box green"><strong>raw/</strong><small>Dữ liệu nguồn</small></div>
      <div class="box green"><strong>bronze/</strong><small>Source + metadata</small></div>
      <div class="box green"><strong>silver/</strong><small>Dữ liệu chuẩn hóa</small></div>
      <div class="box green"><strong>offline/</strong><small>PIT feature tables</small></div>
      <div class="box green"><strong>models/</strong><small>Model có version</small></div>
      <div class="box green"><strong>predictions/</strong><small>Kết quả scoring</small></div>
      <div class="box green"><strong>manifests/</strong><small>Trạng thái và catalog pointer</small></div>
    </div>
  </div>

  <div class="observability">
    <div class="box gray"><strong>Cloud Logging</strong><small>Log của build, workflow và jobs</small></div>
    <div class="box gray"><strong>Cloud Monitoring</strong><small>Runtime, failure, memory và cảnh báo</small></div>
    <div class="box gray"><strong>BigQuery</strong><small>Truy vấn kết quả và phục vụ demo</small></div>
  </div>

  <div class="legend">
    <span><i class="dot" style="background:#4692c6"></i>Compute / điều phối</span>
    <span><i class="dot" style="background:#4f9a6d"></i>Dữ liệu</span>
    <span><i class="dot" style="background:#8b70bd"></i>Docker image</span>
    <span><i class="dot" style="background:#d9973f"></i>Trigger</span>
  </div>
  <div class="footer">Trang 1/2 — GCP Cloud Pipeline Architecture</div>
</section>

<section class="page">
  <h1>Luồng xử lý hằng ngày và trạng thái triển khai</h1>
  <div class="subtitle">Ví dụ ngày 6/11 hệ thống nhận dữ liệu của ngày 5/11 và tạo features/predictions chỉ cho batch mới.</div>

  <div class="second-grid">
    <div>
      <div class="sequence">
        <div class="seq-time">01:00 UTC</div><div class="seq-arrow">→</div>
        <div class="seq-step orange"><strong>Cloud Scheduler kích hoạt Workflow</strong>Truyền <code>processing_date=2026-11-05</code> và version cần sử dụng.</div>

        <div class="seq-time">Bước 1</div><div class="seq-arrow">→</div>
        <div class="seq-step blue"><strong>Bronze ingestion</strong>Đọc raw batch, giữ dữ liệu nguồn, thêm checksum và ingest metadata.</div>

        <div class="seq-time">Bước 2</div><div class="seq-arrow">→</div>
        <div class="seq-step blue"><strong>Silver transformation</strong>Chuẩn hóa schema, join identity, tạo event_time và entity IDs.</div>

        <div class="seq-time">Bước 3</div><div class="seq-arrow">→</div>
        <div class="seq-step blue"><strong>PIT feature materialization</strong>Mỗi observation chỉ nhìn thấy history xảy ra trước PIT cutoff của chính nó.</div>

        <div class="seq-time">Bước 4</div><div class="seq-arrow">→</div>
        <div class="seq-step blue"><strong>Fraud scoring</strong>Đọc model có version, chấm điểm batch mới và ghi predictions/report.</div>

        <div class="seq-time">Publish</div><div class="seq-arrow">→</div>
        <div class="seq-step green"><strong>Quality checks và manifest</strong>Chỉ cập nhật catalog pointer khi row count, schema, checksum và PIT checks đều pass.</div>
      </div>

      <div class="note">
        <strong>Nếu Silver thất bại:</strong> Workflow đánh dấu execution thất bại; PIT Feature và Scoring không chạy.
        Khi sửa xong có thể chạy lại đúng ngày bị lỗi hoặc backfill một time range, không cần chạy lại toàn bộ lịch sử.
      </div>
    </div>

    <div>
      <div class="status-card done">
        <h2>✓ Đã hoàn thành</h2>
        <ul>
          <li>Cloud project, budget và region</li>
          <li>Cloud configuration và JSON logging</li>
          <li>Docker Linux amd64, non-root</li>
          <li>Cloud Build và Artifact Registry</li>
          <li>Private GCS bucket và lifecycle</li>
          <li>Runtime/builder service accounts</li>
          <li>Cloud Run PIT demo: PASS</li>
          <li>Cloud Run ↔ GCS read/write: PASS</li>
        </ul>
      </div>

      <div class="status-card todo">
        <h2>○ Chưa hoàn thành</h2>
        <ul>
          <li>Terraform/import hạ tầng</li>
          <li>Image tag bằng Git commit SHA</li>
          <li>Cloud source/storage configuration</li>
          <li>Bronze, Silver và PIT full-data spike</li>
          <li>Run-scoped publish và catalog pointer</li>
          <li>Workflows và Scheduler</li>
          <li>Scoring, BigQuery và dashboard</li>
          <li>Backfill orchestration</li>
        </ul>
      </div>

      <div class="status-card gray">
        <h2>Bằng chứng hiện có</h2>
        <ul>
          <li>Build: <code>583532b6-d303-403b-ae86-f5018a0bb027</code></li>
          <li>Build runtime: <strong>2m34s</strong></li>
          <li>Image digest: <code>sha256:007eb0a7...</code></li>
          <li>Cloud Run: <code>pit-features-5c8xt</code></li>
          <li>Storage smoke: <code>pit-storage-smoke-w2fps</code></li>
        </ul>
      </div>
    </div>
  </div>
  <div class="footer">Trang 2/2 — GCP Cloud Pipeline Architecture</div>
</section>

</body>
</html>
'@

$tempHtml = Join-Path ([System.IO.Path]::GetTempPath()) "pit-gcp-cloud-architecture.html"
$tempPdf = Join-Path ([System.IO.Path]::GetTempPath()) "pit-gcp-cloud-architecture-$([guid]::NewGuid()).pdf"
[System.IO.File]::WriteAllText($tempHtml, $html, [System.Text.UTF8Encoding]::new($false))
[System.IO.Directory]::CreateDirectory((Split-Path -Parent $outputFile)) | Out-Null

& $edge --headless --disable-gpu --no-pdf-header-footer `
    "--print-to-pdf=$tempPdf" ([System.Uri]$tempHtml).AbsoluteUri | Out-Null

if (-not (Test-Path -LiteralPath $tempPdf)) {
    throw "PDF generation failed before writing output: $outputFile"
}

Move-Item -LiteralPath $tempPdf -Destination $outputFile -Force
Write-Output "Generated: $outputFile"
