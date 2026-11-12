# Pipelines

Các entry point dự kiến:

- `ingest.py`
- `build_silver.py`
- `materialize_features.py`
- `build_training_dataset.py`
- `backfill.py`

Implementation sẽ được bổ sung từ tuần 1–3.

## Dataset inventory và profiling

Sau khi đặt IEEE-CIS CSV trong `data/raw/`, chạy:

```powershell
python pipelines/profile_dataset.py
```

Hoặc dùng console script sau khi cài package editable:

```powershell
profile-ieee-cis
```

Đầu ra:

- `reports/generated/dataset_profile.json`: profile đầy đủ cho máy đọc, không commit.
- `reports/generated/raw_checksums.json`: SHA-256 manifest của raw inputs, không commit.
- `reports/dataset_audit_summary.md`: tóm tắt có thể review và commit.

Có thể chạy một vài source để kiểm tra nhanh:

```powershell
profile-ieee-cis --sources train_transaction train_identity
```

Nếu chỉ thay đổi cách render báo cáo, có thể tái sử dụng profile JSON hiện có mà không đọc lại CSV:

```powershell
python pipelines/profile_dataset.py --reuse-existing-json
```

Để kiểm tra hoặc tạo lại checksum mà không chạy lại toàn bộ profiling:

```powershell
python pipelines/profile_dataset.py --checksum-only
```

## Surrogate entity-key analysis

Sau khi profiling xong, chạy:

```powershell
python pipelines/analyze_entity_keys.py
```

Đầu ra:

- `reports/generated/entity_key_profile.json`: metrics đầy đủ, không commit.
- `reports/entity_key_analysis.md`: báo cáo so sánh candidate keys và giải thích metrics.

Candidate keys được cấu hình trong `configs/entities.yaml`.

## Bronze ingestion

Pipeline đọc raw CSV theo `configs/sources.yaml`, giữ các cột nguồn ở dạng chuỗi,
bổ sung ingestion metadata và ghi Parquet theo cơ chế staging → validate → publish.

Chạy thử một source nhỏ trước:

```powershell
python pipelines/ingest_bronze.py --sources train_identity --progress-every-rows 50000
```

Khi smoke test thành công, chạy toàn bộ bốn source:

```powershell
python pipelines/ingest_bronze.py --progress-every-rows 100000
```

Trong terminal, theo dõi các dòng:

```text
[1/4] ingest ...
[progress] ... rows (...s)
[validated] ... rows, ... columns, ... MB
[bronze] validation passed; publishing staged files
[bronze] success: manifest=...
```

Chỉ coi job thành công khi có dòng `[bronze] success`. Nếu job lỗi trước bước
`publishing`, các file canonical cũ không bị thay thế.

Đầu ra:

- `data/bronze/<source>/data.parquet`: Bronze snapshot của từng source, không commit.
- `reports/generated/bronze_ingestion_manifest.json`: checksum, row count, schema size,
  output path, runtime và run ID, không commit.

Kiểm tra nhanh manifest sau khi chạy:

```powershell
Get-Content reports/generated/bronze_ingestion_manifest.json
```

## Silver transformation

Pipeline đọc bốn Bronze snapshots, chuẩn hóa schema/type, kiểm tra duplicate,
tạo `event_time`, left join identity, thêm hai entity views và ghi canonical
Silver dataset partition theo `dataset_split/event_month`.

Chạy:

```powershell
python pipelines/build_silver.py --memory-limit 4GB
```

Máy ít RAM có thể giảm giới hạn; DuckDB sẽ spill dữ liệu tạm xuống
`data/silver/.duckdb_tmp`:

```powershell
python pipelines/build_silver.py --memory-limit 2GB --threads 2
```

Theo dõi sáu stage trong terminal:

```text
[1/6] validating Bronze inputs and duplicate policy
[2/6] building canonical cast/join/entity SQL
[3/6] writing partitioned Silver Parquet
[4/6] running row, join, type and event-time quality checks
[5/6] publishing canonical Silver dataset
[6/6] success: manifest=...
```

Stage `[3/6]` có thể không in thêm dòng trong khoảng một phút vì DuckDB đang xử lý
toàn bộ bảng rộng. Chỉ coi job thành công khi có `[6/6] success`. Nếu quality check
hoặc fingerprint thất bại, staged output không được publish.

Đầu ra:

- `data/silver/transactions/dataset_split=<...>/event_month=<...>/*.parquet`
- `reports/generated/silver_build_manifest.json`

Kiểm tra manifest và partition:

```powershell
Get-Content reports/generated/silver_build_manifest.json
Get-ChildItem data/silver/transactions -Directory -Recurse
```

Chạy lại cùng lệnh để kiểm tra tính deterministic. Manifest thành công phải có:

```json
"matches_previous_run": true
```

## Feature Registry validation

Validator đọc cả primary và secondary registry, kiểm tra schema của từng feature và
đối chiếu semantics giữa hai entity views.

Chạy:

```powershell
python pipelines/validate_feature_registry.py
```

Hoặc sau khi cài package editable:

```powershell
validate-feature-registry
```

Kết quả thành công:

```text
[valid] configs/features/transaction_velocity_v1.yaml: ... v1, 10 features
[valid] configs/features/transaction_velocity_card_v1.yaml: ... v1, 10 features
[feature-registry] success: 20 output columns
```

Exit code bằng 0 khi cả hai registry hợp lệ. YAML sai sẽ in
`[feature-registry] invalid: ...` và trả exit code 1, phù hợp để chặn CI/pipeline trước
khi tính feature. Bước này chỉ đọc config, không đọc hoặc tạo lại Bronze/Silver data.

## Versioned offline feature table

Materializer đọc Silver Parquet, tạo observations, tính 10 primary + 10 secondary PIT
features và publish một immutable Parquet table theo version.

Chạy:

```powershell
python pipelines/materialize_offline_features.py --feature-table-version 1
```

Theo dõi bốn stage:

```text
[1/4] validating feature registries and loading Silver source
[2/4] computing primary and secondary PIT feature views
[3/4] writing and validating staged Parquet
[4/4] publishing immutable version directory
[offline-store] success: data\offline_store\transaction_features\v1
```

Chỉ coi job thành công khi có dòng `[offline-store] success`. Stage 2 là phần lâu nhất vì
tính rolling history. Output được viết vào staging trước; chỉ publish sau khi row count,
unique `TransactionID`, feature schema và version đều hợp lệ.

Đầu ra mặc định được partition theo ngày của `prediction_time`:

```text
data/offline_store/transaction_features/v1/
  observation_date=YYYY-MM-DD/part_0.parquet
```

`observation_date = CAST(timezone('UTC', prediction_time) AS DATE)`. Việc ép UTC trước khi
lấy ngày ngăn timezone máy chạy làm một UTC day bị tách thành hai partitions. Khi đọc một
time range, DuckDB có thể prune các thư mục ngày không liên quan.

Một version là immutable. Nếu `v1` đã tồn tại, command dừng thay vì ghi đè. Khi feature
definition thay đổi, tăng `--feature-table-version`. Partition, run manifest và bounded
backfill sẽ được bổ sung ở các task tiếp theo của Mốc 6.

Kiểm tra nhanh output:

```powershell
python -c "import duckdb; print(duckdb.sql(\"SELECT COUNT(*), COUNT(DISTINCT TransactionID), MIN(observation_date), MAX(observation_date) FROM read_parquet('data/offline_store/transaction_features/v1/**/*.parquet', hive_partitioning=true)\").fetchall())"
```

Chạy test nhỏ trước khi chạy full Silver:

```powershell
python -m pytest tests/point_in_time/test_offline_materialization.py -v
```

Kết quả yêu cầu là `5 passed`.

### Daily backfill

Backfill một khoảng ngày theo half-open interval `[start_time, end_time)`:

```powershell
python pipelines/materialize_offline_features.py `
  --feature-table-version 1 `
  --backfill `
  --start-time 2017-01-08T00:00:00Z `
  --end-time 2017-01-09T00:00:00Z
```

Backfill đọc Silver history để tính PIT nhưng chỉ tạo observations trong cutoff range. Vì
partition theo ngày, hai boundary bắt buộc là UTC midnight. Partition trong range được ghi
staging, validate rồi **replace**, không append; chạy lại cùng range không tạo duplicate.

Mỗi initial/backfill run tạo manifest tại:

```text
data/offline_store/transaction_features/v1/manifests/<run_id>.json
```

Manifest lưu run ID, mode, source SHA-256, source file count, feature versions, cutoff
`[start inclusive, end exclusive)`, row/partition counts, observation-date range và semantic
fingerprint. Theo dõi terminal giống bốn stage của initial materialization và chỉ coi thành
công khi có `[offline-store] success`.

Test initial materialization, manifest và chạy backfill hai lần:

```powershell
python -m pytest tests/point_in_time/test_offline_materialization.py -v
```

Kết quả hiện tại phải là `5 passed`.

### Legacy offline-store migration

Nếu một project cũ còn layout `v1/features.parquet`, migrate sang UTC daily partitions mà
không tính lại features:

```powershell
python pipelines/migrate_offline_store.py `
  --version-directory data/offline_store/transaction_features/v1 `
  --feature-table-version 1
```

Migration ghi staging, reconcile rows/unique IDs/version, rồi atomic-swap toàn bộ version
directory. Chỉ khi có `[offline-migration] success` thì legacy file và mixed backfill
partitions mới bị loại. Manifest migration được giữ trong `v1/manifests/`.

## Temporal model split audit

Chính sách cố định chia labeled train transactions theo `TransactionDT`, tuyệt đối không
random split:

```text
train         : TransactionDT < 10454400
validation    : 10454400 <= TransactionDT < 13132800
internal_test : TransactionDT >= 13132800
```

Chạy full-data audit:

```powershell
python pipelines/analyze_temporal_split.py
```

Theo dõi ba dòng `[train]`, `[validation]`, `[internal_test]`, sau đó phải có:

```text
[temporal-split] success: report=reports\generated\temporal_split_report.json
```

Report chứa row proportion, `TransactionDT` range, fraud count/rate và quality checks.
Policy giải thích tại `docs/temporal_split_policy.md`; boundary/config machine-readable tại
`configs/training_split.yaml`.

## Train-only preprocessing fit

Fit raw-baseline median và categorical vocabulary chỉ bằng temporal train period:

```powershell
python pipelines/fit_preprocessor.py
```

Theo dõi output:

```text
[preprocessing] config=fraud_baseline_preprocessor_v1 v1
[fit] rows=414542, TransactionDT < 10454400
[preprocessing] semantic_sha256=...
[preprocessing] success: artifact=..., report=...
```

Artifact local nằm tại `artifacts/preprocessing/v1/preprocessor.json`; audit report tại
`reports/generated/preprocessing_fit_report.json`. Cả hai không commit. Validation và
internal test chỉ được audit/transform: chúng không được tính median, không thêm category
vào vocabulary. Policy đầy đủ nằm tại `docs/preprocessing_policy.md`.

Chạy test chứng minh leakage guard:

```powershell
python -m pytest tests/unit/test_preprocessing.py -v
```

Test cố ý đặt amount/category khác biệt trong validation và xác nhận chúng không ảnh hưởng
train median/vocabulary. Kết quả yêu cầu là `3 passed`.

## Model training dataset

Join labeled Silver với offline PIT feature table, áp dụng train-only preprocessing và ghi
dataset partition theo `model_split`:

```powershell
python pipelines/build_training_dataset.py
```

Theo dõi:

```text
[1/5] validating sources, versions and one-to-one join
[2/5] fitting nullable PIT medians on temporal train only
[3/5] applying locked raw preprocessing and PIT null policy
[4/5] writing and reconciling partitioned Parquet
[5/5] publishing immutable training dataset version
[training-dataset] success: data\training\model_dataset\v1
```

Output:

```text
data/training/model_dataset/v1/
  model_split=train/
  model_split=validation/
  model_split=internal_test/
  manifests/
```

Stage 1 fail nếu join thiếu feature hoặc nhân dòng. Stage 2 chỉ dùng train rows. Stage 3
khóa categorical vocabulary, impute PIT null và thêm missing indicators. Chỉ coi hoàn tất
khi có dòng `[training-dataset] success`. Chi tiết schema, medians và quality metrics nằm
tại `docs/training_dataset.md`.

Chạy integration tests:

```powershell
python -m pytest tests/unit/test_training_dataset.py -v
```

Kết quả yêu cầu là `2 passed`.

## Train raw baseline và raw + PIT MVP

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"
python -c "import sys; print(sys.executable)"
python -m pip install -e ".[dev]"
python pipelines/train_baseline_models.py
```

Pipeline train tuần tự:

1. `raw_baseline`: 15 raw features;
2. `raw_plus_pit_mvp`: 15 raw + 20 PIT + 20 PIT missing indicators.

Theo dõi AUC được in mỗi 25 iterations. Internal test không được đọc trong run này. Thành
công khi thấy:

```text
[model-training] success: models\fraud_detection\v1
```

Model bundle là immutable. Chi tiết contract, kết quả và artifact nằm tại
`docs/model_training.md`.

## Đánh giá model

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"
python -c "import sys; print(sys.executable)"
python -m pip install -e ".[dev]"
python pipelines/evaluate_baseline_models.py
```

Pipeline kiểm tra model checksum, chấm cả hai model trên validation và internal test, sau đó
ghi metric JSON cùng prediction Parquet. Theo dõi đến khi thấy:

```text
[model-evaluation] success: reports\generated\model_evaluation\v1
```

Chi tiết định nghĩa metric và kết quả nằm tại `docs/model_evaluation.md`.

## Hoàn tất Mốc 7

So sánh theo `entity_resolution_level` và xuất reproducibility manifest:

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"
python -c "import sys; print(sys.executable)"
python -m pip install -e ".[dev]"
python pipelines/complete_milestone_seven.py
```

Thành công khi thấy:

```text
[milestone-7] success: reports\generated\milestone_seven\v1
```

Đọc kết quả tại `docs/milestone_seven_summary.md`.

## Mốc 8 hardening audit

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"
python -c "import sys; print(sys.executable)"
python -m pip install -e ".[dev]"
python pipelines/run_hardening_audit.py
```

Pipeline audit leakage contracts, benchmark baseline/optimized backfill, kiểm tra semantic
equivalence và ghi JSONL audit log. Thành công khi thấy:

```text
[hardening] success: reports\generated\hardening\v1
```

Chi tiết và cách diễn giải benchmark nằm tại `docs/hardening_report.md`.

