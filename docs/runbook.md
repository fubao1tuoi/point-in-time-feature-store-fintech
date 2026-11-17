# Runbook vận hành pipeline

## 1. Mục đích

Runbook hướng dẫn chuẩn bị, chạy, theo dõi và xử lý lỗi cho pipeline. Các lệnh dùng Windows
PowerShell và được chạy từ project root.

## 2. Chuẩn bị môi trường

```powershell
cd "D:\AITC VinUni\Fintech project"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& ".\.venv\Scripts\Activate.ps1"
python -c "import sys; print(sys.executable)"
```

Python phải trỏ vào `.venv\Scripts\python.exe`. Nếu chưa cài project:

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Kiểm tra bốn raw files:

```powershell
Get-ChildItem data/raw/*.csv | Select-Object Name,Length
```

Không đặt `kaggle.json`, secret hoặc credential trong repository.

## 3. Chạy end-to-end trên clone sạch

Runner chỉ dùng cho workspace chưa có artifact `v1`:

```powershell
& ".\scripts\run_end_to_end.ps1" -MemoryLimit 4GB -Threads 4
```

Bỏ profiling nếu muốn giảm thời gian:

```powershell
& ".\scripts\run_end_to_end.ps1" -MemoryLimit 4GB -Threads 4 -SkipProfiling
```

Chỉ coi run thành công khi terminal có `[end-to-end] success`.
Runner cũng thực thi demo future-event invariance trước full test suite.

## 4. Theo dõi trong khi chạy

Mỗi stage in số thứ tự và tên. Bước tính offline PIT features thường lâu nhất và chỉ ghi file
từ stage `[3/4] writing and validating staged Parquet`.

```powershell
Get-Process python -ErrorAction SilentlyContinue |
  Select-Object Id,CPU,
    @{Name="RAM_GB";Expression={[math]::Round($_.WorkingSet64/1GB,2)}},
    StartTime,Responding
```

Nếu `CPU` tiếp tục tăng thì process vẫn làm việc. Không chạy hai full materialization cùng lúc
trên máy 16 GB RAM.

## 5. Kiểm tra sau khi chạy

```powershell
python -m pytest
python -m ruff check .
git diff --check
```

```powershell
Get-Content reports/generated/silver_build_manifest.json
Get-Content reports/generated/model_evaluation/v1/evaluation_report.json
Get-Content reports/generated/milestone_seven/v1/reproducibility_manifest.json
Get-Content reports/generated/hardening/v1/hardening_report.json
```

Điều kiện tối thiểu: không trùng `TransactionID`, đủ ba temporal splits,
`internal_test_used=false` khi train, hardening status `success`, test và Ruff pass.

## 6. Demo future-event invariance

```powershell
python pipelines/demo_future_event_invariance.py
```

Kết quả mong đợi:

```text
[future-event-demo] observation: TransactionID=200 at 10:00 UTC
[future-event-demo] appended future event: TransactionID=300 at 11:00 UTC
[future-event-demo] compared features: 10
[future-event-demo] PASS: all past feature values remained unchanged
```

Xem đầy đủ feature trước/sau:

```powershell
python pipelines/demo_future_event_invariance.py --json
```

## 7. Bounded backfill

```powershell
python pipelines/materialize_offline_features.py `
  --feature-table-version 1 `
  --backfill `
  --start-time "2017-01-08T00:00:00Z" `
  --end-time "2017-01-09T00:00:00Z"
```

Boundary phải là UTC midnight. Backfill ghi staging, backup partition cũ, validate rồi mới
publish. Không tự xóa partition trước khi gọi pipeline.

## 8. Xử lý lỗi thường gặp

### `ModuleNotFoundError: pit_feature_store`

```powershell
& ".\.venv\Scripts\Activate.ps1"
python -m pip install -e ".[dev]"
```

### `version already exists`

Workspace đã có immutable artifact. Dùng clone sạch để dry-run hoặc tăng version cho experiment
mới; không xóa artifact chỉ để chạy lại.

### Offline computation chạy lâu

Kiểm tra CPU/RAM bằng lệnh ở mục 4. Đóng ứng dụng nặng và chờ nếu CPU vẫn tăng.

### Checksum hoặc fingerprint thay đổi

Dừng publish. So sánh raw checksum, config, commit, dependency version và runtime metadata.
Không sửa manifest thủ công để ép pipeline pass.

### Conflicting duplicate `TransactionID`

Pipeline fail có chủ đích. Cách ly row xung đột, xác định record đúng từ nguồn và ingest lại;
không chọn ngẫu nhiên một row.

### Job fail giữa lúc publish

Kiểm tra staging/backup và failure audit log. Không di chuyển file thủ công khi chưa xác định
trạng thái.

## 9. Khôi phục và rollback

- Bronze/Silver: dựng lại từ raw files có checksum đã biết.
- Offline backfill: tự phục hồi partition cũ nếu thay thế thất bại.
- Model/dataset: consumer tiếp tục dùng immutable version trước.
- Config/code: checkout commit ghi trong reproducibility manifest.

## 10. Checklist phát hành

- [x] Test, Ruff và `git diff --check` pass.
- [x] Demo future-event invariance pass.
- [x] Metric trong báo cáo khớp evaluation JSON.
- [x] Architecture, feature catalog, runbook và slide đã cập nhật.
- [x] Clean-clone dry-run có bằng chứng row count/metric khớp.
- [x] Không stage raw data, model binary, secret hoặc paper nguồn.
- [x] Commit cuối nằm trên `main` và release tag trỏ đúng commit.
