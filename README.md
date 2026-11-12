# Point-in-Time Correct Feature Store

Feature platform MVP tạo historical features đúng theo thời điểm dự báo, không để dữ liệu
tương lai đi ngược vào quá khứ. IEEE-CIS Fraud Detection được dùng làm dataset kiểm chứng;
trọng tâm của project là PIT correctness, versioning, reproducibility, backfill và data
engineering, không phải xây một fraud product hoàn chỉnh.

## Kết quả hiện tại

- Bronze/Silver data foundation có lineage metadata và data-quality checks.
- Hai surrogate entity views: `card1 + addr1` và fallback `card1`.
- 20 historical PIT features: 10 logical features × 2 entity views.
- Offline feature table partition theo UTC observation date, hỗ trợ bounded backfill.
- Model-ready dataset gồm 590.540 transactions và temporal split 70/15/15.
- CatBoost raw baseline so với raw + PIT MVP.
- Internal-test ROC-AUC: `0,815880 → 0,829082`.
- Internal-test PR-AUC: `0,236695 → 0,254277`.
- 91 automated tests cho data contract, PIT correctness, edge cases và failure handling.

Chi tiết tiến độ nằm tại [PROJECT_PROGRESS.md](PROJECT_PROGRESS.md).

## Kiến trúc

```text
IEEE-CIS CSV
    ↓
Bronze Parquet + ingest metadata
    ↓
Silver transactions
    ├── event_time
    ├── identity left join
    └── primary/secondary entity IDs
    ↓
PIT feature computation
    ↓
Versioned offline feature store
    ↓
Temporal training dataset
    ↓
Raw baseline vs Raw + PIT CatBoost
    ↓
Evaluation, leakage audit and reproducibility manifests
```

Xem sơ đồ chi tiết tại [docs/architecture.md](docs/architecture.md).

## Yêu cầu

- Windows PowerShell.
- Python 3.11.
- Khoảng 8 GB RAM được khuyến nghị; có thể giảm DuckDB memory limit nếu cần.
- IEEE-CIS Fraud Detection CSV đã tải từ
  [Kaggle](https://www.kaggle.com/competitions/ieee-fraud-detection/data).

Dataset, model và generated artifacts không được commit vào Git.

## 1. Clone và thiết lập môi trường

```powershell
git clone <URL_REPOSITORY_CUA_BAN>
cd "Fintech project"

python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& ".\.venv\Scripts\Activate.ps1"

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -c "import sys; print(sys.executable)"
```

Python executable phải trỏ vào `<project>\.venv\Scripts\python.exe`.

Nếu chạy trên máy hiện tại:

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"
```

## 2. Chuẩn bị dữ liệu

Đặt đúng bốn file vào `data/raw/`:

```text
data/raw/train_transaction.csv
data/raw/train_identity.csv
data/raw/test_transaction.csv
data/raw/test_identity.csv
```

Kiểm tra:

```powershell
Get-ChildItem data/raw/*.csv | Select-Object Name,Length
```

Không đặt `kaggle.json` trong repository và không commit raw data.

## 3. Chạy end-to-end tự động trên workspace sạch

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"
& ".\scripts\run_end_to_end.ps1" -MemoryLimit 4GB -Threads 4
```

Nếu muốn bỏ profiling để tiết kiệm thời gian:

```powershell
& ".\scripts\run_end_to_end.ps1" -MemoryLimit 4GB -Threads 4 -SkipProfiling
```

Script chạy tuần tự từ raw profiling tới hardening audit và chỉ dành cho workspace chưa có
các output version `v1`. Nó chủ động dừng nếu Bronze/Silver, offline store, training dataset,
model hoặc report v1 đã tồn tại; script không xóa và không ghi đè artifact cũ.

Theo dõi stage dạng:

```text
[01/14] Dataset profiling
[02/14] Entity-key analysis
...
[14/15] Full test suite
[15/15] Ruff lint
[end-to-end] success
```

Pipeline train model có thể mất vài phút. Chỉ coi toàn bộ run thành công khi thấy dòng cuối.

## 4. Các lệnh end-to-end thủ công

Chạy trong project root sau khi bật `.venv`:

```powershell
# 1. Inventory, profiling và raw checksum
python pipelines/profile_dataset.py

# 2. Phân tích surrogate entities
python pipelines/analyze_entity_keys.py

# 3. Raw CSV → Bronze Parquet
python pipelines/ingest_bronze.py --progress-every-rows 100000

# 4. Bronze → canonical Silver
python pipelines/build_silver.py --memory-limit 4GB --threads 4

# 5. Validate 20 PIT output definitions
python pipelines/validate_feature_registry.py

# 6. Materialize offline feature table v1
python pipelines/materialize_offline_features.py --feature-table-version 1

# 7. Audit temporal train/validation/internal-test split
python pipelines/analyze_temporal_split.py

# 8. Fit preprocessing chỉ bằng temporal train
python pipelines/fit_preprocessor.py

# 9. Join Silver + offline PIT features thành model-ready dataset
python pipelines/build_training_dataset.py

# 10. Train raw baseline và raw + PIT MVP
python pipelines/train_baseline_models.py

# 11. Evaluate validation và held-out internal test
python pipelines/evaluate_baseline_models.py

# 12. Subgroup comparison + reproducibility manifest
python pipelines/complete_milestone_seven.py

# 13. Leakage audit, edge hardening và optimization equivalence
python pipelines/run_hardening_audit.py

# 14. Regression tests và lint
python -m pytest
python -m ruff check .
```

Không bỏ qua thứ tự: bước sau phụ thuộc artifact/version của bước trước.

## 5. Output chính

| Output | Vị trí |
|---|---|
| Bronze snapshots | `data/bronze/<source>/data.parquet` |
| Silver transactions | `data/silver/transactions/` |
| Offline PIT table | `data/offline_store/transaction_features/v1/` |
| Preprocessing artifact | `artifacts/preprocessing/v1/preprocessor.json` |
| Model-ready dataset | `data/training/model_dataset/v1/` |
| CatBoost models | `models/fraud_detection/v1/` |
| Evaluation report/predictions | `reports/generated/model_evaluation/v1/` |
| Reproducibility manifest | `reports/generated/milestone_seven/v1/` |
| Hardening report/audit log | `reports/generated/hardening/v1/` |

## 6. Workspace hiện tại đã có v1

Project dùng immutable versions. Trên workspace đã chạy xong, các lệnh materialize, train và
evaluate sẽ báo `version already exists`. Đây là cơ chế bảo vệ artifact, không phải lỗi.

Không xóa output chỉ để chạy lại. Để kiểm tra workspace hiện tại:

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"

python -m pytest
python -m ruff check .
Get-Content reports/generated/model_evaluation/v1/evaluation_report.json
Get-Content reports/generated/milestone_seven/v1/reproducibility_manifest.json
Get-Content reports/generated/hardening/v1/hardening_report.json
```

Muốn tạo experiment mới phải tăng version trong các config liên quan và dùng output version
mới; không ghi đè `v1` đã dùng để báo cáo.

## 7. Bounded backfill

Ví dụ tính lại feature cho một ngày UTC:

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"

python pipelines/materialize_offline_features.py `
  --feature-table-version 1 `
  --backfill `
  --start-time "2017-01-08T00:00:00Z" `
  --end-time "2017-01-09T00:00:00Z"
```

Backfill thay đúng daily partition, có backup/rollback và kiểm tra không duplicate. Late event
chỉ làm thay đổi past feature khi khoảng bị ảnh hưởng được backfill có chủ đích.

## 8. Quy tắc correctness quan trọng

- Mỗi transaction là một observation tại `prediction_time = event_time`.
- History phải thỏa `(event_time, TransactionID) < observation tuple`.
- Current event và future events luôn bị loại.
- Window start là inclusive; cutoff phía observation là strict.
- Preprocessing chỉ fit trên train.
- Temporal evaluation không dùng random split.
- Internal test không được dùng để train hoặc chọn iteration.
- Mỗi versioned dataset/model/report là immutable.

## 9. Cấu trúc repository

```text
configs/     Data, entity, feature, split, preprocessing và model contracts
data/        Raw/processed local data; bị Git ignore
docs/        Thiết kế, policy, implementation log và báo cáo
pipelines/   Python CLI entry points
scripts/     PowerShell helpers/orchestration
src/         Production implementation
tests/       Unit, integration, data-quality và PIT correctness tests
reports/     Generated reports, benchmarks và audit evidence
```

## 10. Tài liệu liên quan

- [Implementation log](docs/IMPLEMENTATION_LOG.md)
- [PIT time policy](docs/pit_time_policy.md)
- [Feature catalog](docs/feature_catalog.md)
- [Training dataset](docs/training_dataset.md)
- [Model training](docs/model_training.md)
- [Model evaluation](docs/model_evaluation.md)
- [Mốc 7 summary](docs/milestone_seven_summary.md)
- [Mốc 8 hardening report](docs/hardening_report.md)
- [Pipeline command reference](pipelines/README.md)

## 11. Git và dữ liệu nhạy cảm

Không commit IEEE-CIS CSV/Parquet, `kaggle.json`, `.env`, trained model binaries, local
database/runtime volumes hoặc generated reports có runtime lineage. Chỉ commit code, config,
tests và tài liệu có thể dùng để tái tạo artifact.
