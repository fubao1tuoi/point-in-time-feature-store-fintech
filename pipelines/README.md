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

