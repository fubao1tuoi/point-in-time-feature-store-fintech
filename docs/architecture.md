# Kiến trúc Point-in-Time Correct Feature Store

## 1. Mục tiêu kiến trúc

Hệ thống tạo historical features cho từng giao dịch tại đúng thời điểm dự báo. Mọi bước phải
truy vết được dữ liệu nguồn, chạy lại có kiểm soát, không dùng dữ liệu tương lai và không làm
thay đổi âm thầm artifact đã công bố.

## 2. Luồng xử lý hiện tại

```text
IEEE-CIS CSV
    │
    ├── SHA-256 + profiling + entity analysis
    ▼
Bronze Parquet
    │  giữ nguyên cột nguồn + ingest metadata
    ▼
Silver transactions
    │  cast type, deduplicate, identity left join
    │  event_time, entity IDs, routing metadata
    ▼
Observation layer
    │  một TransactionID = một observation
    │  prediction_time = event_time
    ▼
PIT feature engine
    │  primary: card1 + addr1 → 10 card_addr_* features
    │  secondary: card1       → 10 card_* features
    ▼
Offline feature store v1
    │  Parquet partition theo observation_date UTC
    │  manifest + version + bounded backfill
    ▼
Training dataset v1
    │  15 raw + 20 PIT + 20 missing indicators
    │  temporal split 70% / 15% / 15%
    ▼
CatBoost models
    │  raw baseline ↔ raw + PIT MVP
    ▼
Evaluation + leakage audit + reproducibility manifest
```

## 3. Quy tắc PIT trung tâm

Một history row chỉ được dùng cho observation khi:

```text
(history.event_time, history.TransactionID)
    <
(observation.prediction_time, observation.TransactionID)
```

So sánh tuple loại transaction tương lai, không cho current transaction tự tính vào lịch sử
của chính nó và sắp ổn định các transaction cùng timestamp bằng `TransactionID`. Window start
là inclusive, nhưng cutoff phía observation luôn strict.

## 4. Các tầng dữ liệu

### Raw và Bronze

Bốn CSV gốc được giữ ngoài Git. SHA-256 chứng minh lần chạy dùng đúng input. Bronze giữ dữ
liệu nguồn và thêm source file, checksum, ingest run ID, ingest time và source row number.

### Silver

Silver tạo schema chuẩn, kiểm soát duplicate `TransactionID`, left join identity, tạo
`event_time`, hai entity ID và routing metadata. Dữ liệu được partition theo `dataset_split`
và `event_month`.

### Offline feature store

Mỗi row đại diện cho feature của một transaction tại `prediction_time`. Output có version và
partition theo ngày UTC. Full materialization tạo version mới; bounded backfill chỉ thay đúng
partition ngày được yêu cầu bằng staging, backup và rollback.

### Training và model

Training dataset chỉ lấy train transactions có label. Preprocessing fit trên train period;
validation dùng early stopping; internal test chỉ dùng đánh giá cuối. Hai model dùng cùng
CatBoost configuration để cô lập giá trị bổ sung của PIT features.

## 5. Primary và secondary entity views

```text
card_address_entity_id = hash(card1, addr1)
card_entity_id         = hash(card1)
```

Primary cụ thể hơn nhưng thiếu khi `addr1` null. Secondary có coverage cao hơn nhưng có thể
gom nhiều giao dịch hơn. Model nhận cả hai feature sets và missing indicators.

## 6. Versioning, lineage và quality gates

Contract được lưu bằng YAML. Dataset, feature table, preprocessing và model dùng version không
ghi đè. Manifest ghi row count, cutoff, checksum, feature list, tham số và SHA-256 artifact.

```text
Raw checksum
  → Bronze reconciliation
  → Silver row count / uniqueness / left-join checks
  → Feature Registry validation
  → golden PIT tests
  → offline grain / partition checks
  → temporal split and train-only preprocessing checks
  → held-out evaluation
  → leakage/hardening audit
```

Nếu quality gate thất bại, pipeline không publish staging output và giữ failure audit log.

## 7. Kiến trúc Google Cloud dự kiến

```text
Daily file → Cloud Storage raw
                    │
Cloud Scheduler → Workflows
                    │
                    ▼
          Cloud Run Jobs (Docker)
 ingest → Bronze → Silver → PIT → prediction
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
 Cloud Storage            BigQuery
 versioned Parquet        query/demo
          │
 Cloud Logging + Monitoring
```

Artifact Registry lưu Docker image; Cloud Build test/build image; Secret Manager và IAM quản
lý secret/quyền. Đây là kế hoạch triển khai, không phải kết quả đã deploy trong bản local.

## 8. Phạm vi MVP

MVP là offline batch feature platform. Online low-latency serving và real-time streaming không
thuộc phạm vi bắt buộc. Trọng tâm là PIT correctness, reproducibility, safe backfill và khả
năng vận hành batch hằng ngày.

