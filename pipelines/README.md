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

