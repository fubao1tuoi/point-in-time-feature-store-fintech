# Project Progress Tracker

> Đây là file theo dõi tiến độ chính của project. Sau mỗi lần hoàn thành công việc, tick `[x]`, cập nhật cột **Bằng chứng** và chuyển mục **Việc tiếp theo**. Kế hoạch chi tiết nằm trong [`PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md`](./PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md); giải thích các phần đã triển khai, cách chạy và kết quả thực tế được cập nhật liên tục tại [`docs/IMPLEMENTATION_LOG.md`](./docs/IMPLEMENTATION_LOG.md).

## 1. Trạng thái hiện tại

```text
Giai đoạn hiện tại : Tuần 2 — Point-in-Time feature computation
Đã hoàn thành       : Audit + entities + Bronze/Silver + Feature Registry/golden dataset
Đang làm tiếp       : PIT feature engine trên golden dataset
Mục tiêu gần nhất   : Golden feature tests pass 100% trước khi chạy full data
```

## 2. Quy trình tổng thể

```text
Đề cương và phạm vi
        ↓
Dataset inventory / profiling
        ↓
Data dictionary
        ↓
Entity-key analysis
        ↓
Bronze và Silver pipeline
        ↓
Feature Registry + golden dataset
        ↓
Point-in-Time feature engine          ← BƯỚC TIẾP THEO
        ↓
Offline feature store + backfill
        ↓
Chronological training dataset
        ↓
Baseline model + leakage audit
        ↓
Benchmark, tối ưu, tài liệu và demo
```

## 3. Checklist thực hiện lần lượt

### Mốc 0 — Khởi tạo và chốt bài toán

- [x] Chốt đề tài Point-in-Time Correct Feature Store.
- [x] Chốt dataset IEEE-CIS Fraud Detection.
- [x] Viết project proposal và output mong đợi.
- [x] Tạo repository structure, môi trường Python và `.gitignore`.
- [x] Chốt lộ trình 5 tuần.

**Bằng chứng:**

- [`docs/project_proposal.md`](./docs/project_proposal.md)
- [`PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md`](./PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md)
- [`pyproject.toml`](./pyproject.toml)

### Mốc 1 — Hiểu và kiểm kê dữ liệu

- [x] Tải và đặt dữ liệu ngoài Git.
- [x] Viết script inventory/profiling chạy tự động.
- [x] Kiểm tra số dòng, số cột, schema và dung lượng file.
- [x] Kiểm tra `TransactionID`, `isFraud`, identity coverage và `TransactionDT`.
- [x] Tính null rate và cardinality.
- [x] Xuất báo cáo JSON/Markdown.
- [x] Viết data dictionary dựa trên mô tả chính thức của dataset.
- [x] Bổ sung checksum manifest SHA-256 cho các raw files.

**Bằng chứng:**

- [`pipelines/profile_dataset.py`](./pipelines/profile_dataset.py)
- [`src/pit_feature_store/profiling.py`](./src/pit_feature_store/profiling.py)
- [`reports/dataset_audit_summary.md`](./reports/dataset_audit_summary.md)
- [`reports/generated/dataset_profile.json`](./reports/generated/dataset_profile.json)
- [`docs/data_dictionary.md`](./docs/data_dictionary.md)

### Mốc 2 — Chốt surrogate entities

- [x] Phân tích các candidate keys.
- [x] Đo coverage, cardinality, singleton, repeat coverage, skew và temporal span.
- [x] Chọn primary entity: `card1 + addr1`.
- [x] Chọn secondary entity: `card1`.
- [x] Chốt model nhận hai feature sets có prefix riêng.
- [x] Viết hàm hash deterministic và unit tests.
- [x] Chốt routing metadata và null policy.

**Bằng chứng:**

- [`reports/entity_key_analysis.md`](./reports/entity_key_analysis.md)
- [`docs/entity_key_decision.md`](./docs/entity_key_decision.md)
- [`configs/entities.yaml`](./configs/entities.yaml)
- [`src/pit_feature_store/entities.py`](./src/pit_feature_store/entities.py)
- [`tests/unit/test_entities.py`](./tests/unit/test_entities.py)

### Mốc 3 — Xây Bronze/Silver data foundation

- [x] Viết và validate cấu hình source paths cùng synthetic epoch UTC.
- [x] Viết Bronze ingestion giữ nguyên giá trị nguồn và bổ sung metadata ingest.
- [x] Tạo checksum manifest SHA-256 cho raw inputs.
- [x] Viết Silver transformation: cast type và deduplicate có kiểm soát.
- [x] Tạo `event_time = synthetic_epoch + TransactionDT seconds`.
- [x] Left join transaction với identity và tạo `has_identity`.
- [x] Thêm cả hai entity IDs và routing metadata vào Silver.
- [x] Ghi `silver_transactions` ra Parquet, partition theo thời gian phù hợp.
- [x] Viết data-quality tests cho row count, uniqueness, event time và left join.
- [x] Kiểm tra chạy lại cho kết quả logic giống nhau.

**Hoàn thành khi:** có thể chạy một command để tạo canonical `silver_transactions` mà không mất transaction và tất cả quality tests pass.

**Bằng chứng Bronze ingestion:**

- [`pipelines/ingest_bronze.py`](./pipelines/ingest_bronze.py)
- [`src/pit_feature_store/bronze.py`](./src/pit_feature_store/bronze.py)
- [`tests/unit/test_bronze.py`](./tests/unit/test_bronze.py)
- Runtime manifest local: `reports/generated/bronze_ingestion_manifest.json`
- Kết quả full run ngày 2026-11-05: 4/4 sources thành công, checksum khớp raw
  manifest, 1.383.371 rows được ghi vào Bronze Parquet.

**Bằng chứng Silver transformation:**

- [`pipelines/build_silver.py`](./pipelines/build_silver.py)
- [`src/pit_feature_store/silver.py`](./src/pit_feature_store/silver.py)
- [`tests/unit/test_silver.py`](./tests/unit/test_silver.py)
- Runtime manifest local: `reports/generated/silver_build_manifest.json`
- Kết quả full run ngày 2026-11-05: 1.097.231 transactions, 14 monthly
  partitions, 0 duplicate/conflicting IDs, identity coverage khớp source.
- Hai full runs liên tiếp có cùng semantic fingerprint
  `rows=1097231;xor64=1668359128455216076` theo thuật toán v3 loại run/timestamp
  metadata động.

### Mốc 4 — Feature Registry và golden dataset

- [x] Tạo khung YAML cho primary và secondary transaction velocity features.
- [x] Chốt quy tắc same timestamp bằng thứ tự `(event_time, TransactionID)`.
- [x] Chốt 10 feature MVP cho cả hai entity views (20 output columns).
- [x] Viết schema/model validate feature definitions.
- [x] Viết `docs/feature_catalog.md`.
- [x] Tạo golden dataset nhỏ bằng tay.
- [x] Tạo expected result cho no-history, boundary, same-time, null entity và future event.

**Hoàn thành khi:** YAML sai bị từ chối tự động và expected values của golden dataset được review bằng tay.

### Mốc 5 — Point-in-Time feature computation

- [x] Dùng mỗi transaction làm observation tại `prediction_time = event_time`.
- [x] Tính `card_addr_*` theo primary entity.
- [x] Tính `card_*` theo secondary entity.
- [x] Chỉ dùng lịch sử thỏa PIT cutoff theo `(event_time, TransactionID)`.
- [x] Xử lý đúng window boundary và same timestamp.
- [x] Giữ observation không có history bằng left PIT semantics.
- [x] Viết golden tests và append-only invariance test.
- [x] Chứng minh thêm future rows không làm đổi feature của past rows.

**Hoàn thành khi:** golden tests pass 100%, số output bằng số observations và không có cutoff violation.

### Mốc 6 — Offline feature store và backfill

- [x] Materialize feature table có version ra Parquet.
- [x] Partition theo `observation_date` để hỗ trợ đọc theo time range.
- [x] Lưu run ID, source checksum, feature version, row count và cutoff range.
- [x] Viết backfill command nhận `start_time` và `end_time`.
- [x] Kiểm tra backfill idempotent, không tạo duplicate.

### Mốc 7 — Training dataset và baseline model

- [ ] Chia train/validation/internal-test theo `TransactionDT`.
- [ ] Fit preprocessing chỉ trên training period.
- [ ] Xây training dataset từ offline PIT features.
- [ ] Train raw-feature baseline.
- [ ] Train raw + PIT-feature MVP nhận cả hai feature sets.
- [ ] Đánh giá ROC-AUC, PR-AUC, Recall@FPR và Precision@K.
- [ ] So sánh model theo toàn bộ dữ liệu và theo `entity_resolution_level`.
- [ ] Xuất dataset/model manifest có thể tái lập.

### Mốc 8 — Leakage audit, tối ưu và hardening

- [ ] Audit future aggregation, preprocessing và temporal overlap.
- [ ] Kiểm thử null entity, skew, ties và late/future records.
- [ ] Benchmark runtime và lượng dữ liệu scan trước tối ưu.
- [ ] Áp dụng partition pruning và semi-join reduction.
- [ ] Chứng minh output trước/sau tối ưu tương đương.
- [ ] Hoàn thiện audit log và failure handling.

### Mốc 9 — Tài liệu và demo cuối

- [ ] Hoàn thiện README và lệnh chạy end-to-end.
- [ ] Hoàn thiện architecture, feature catalog và runbook.
- [ ] Viết báo cáo kết quả correctness, model và performance.
- [ ] Làm slide.
- [ ] Chuẩn bị demo future event bị loại khỏi past features.
- [ ] Dry-run từ môi trường sạch.
- [ ] Dọn repo và tạo release/tag cuối.

## 4. Việc tiếp theo

Tiếp tục **Mốc 7 — Training dataset và baseline model**, theo thứ tự:

1. Chốt temporal train/validation/internal-test split.
2. Xây training dataset bằng cách join Silver với offline PIT feature table v1.

Mốc 6 đã hoàn thành versioned/partitioned offline table, lineage manifest và idempotent
daily backfill contract. Trước Mốc 7 cần materialize full Silver feature table v1.

## 5. Nhật ký cập nhật

| Ngày | Thay đổi | Bước tiếp theo |
|---|---|---|
| 2026-11-03 | Hoàn thành profiling, data dictionary và chốt primary/secondary entities cho MVP. | Xây Bronze/Silver pipeline. |
| 2026-11-03 | Bổ sung streaming SHA-256 và `raw_checksums.json` cho raw inputs. | Xây Bronze ingestion và lưu checksum vào metadata. |
| 2026-11-04 | Chốt source-config contract v1 và synthetic epoch `2017-01-01T00:00:00Z`, có validation tự động. | Xây Bronze ingestion. |
| 2026-11-05 | Hoàn thành streaming Bronze ingestion với staging, SHA-256, lineage metadata và Parquet reconciliation. | Chạy Bronze ingestion trên dữ liệu thật, sau đó xây Silver transformation. |
| 2026-11-05 | Hoàn thành Silver transformation, left identity join, event time, entity routing, partitioning, quality checks và deterministic rerun. | Thiết kế Feature Registry validator và golden PIT dataset. |
| 2026-11-06 | Chốt lexicographic PIT cutoff `(event_time, TransactionID)`, current-event exclusion và inclusive window-start boundary. | Chốt 8–12 feature MVP cho hai entity views. |
| 2026-11-06 | Chốt 10 logical historical features cho cả primary và secondary views, gồm velocity, amount, recency và product diversity. | Viết schema/validator cho Feature Registry. |
| 2026-11-09 | Hoàn thành Pydantic Feature Registry schema, CLI validator, cross-view consistency checks và negative unit tests. | Viết feature catalog. |
| 2026-11-09 | Hoàn thành Feature Catalog v1 cho 10 logical features, 2 entity views và 20 output columns. | Tạo golden dataset và expected PIT outputs tính bằng tay. |
| 2026-11-09 | Tạo golden input 10 transactions bằng tay, bao phủ boundary, ties, null, entity isolation và physical-order independence. | Tính expected 20-feature outputs bằng tay. |
| 2026-11-09 | Hoàn thành và review 200 golden expected values cho 10 observations × 20 feature columns; independent cross-check khớp toàn bộ. | Xây PIT feature engine và chạy golden tests. |
| 2026-11-09 | Hoàn thành observation layer: một transaction thành một observation, `prediction_time = event_time`, có grain/time quality checks. | Tính primary `card_addr_*` features trên golden dataset. |
| 2026-11-10 | Hoàn thành Mốc 5: tính đủ 20 PIT features, golden oracle, boundary/same-time, no-history, append-only invariance và deterministic-rerun tests. | Thiết kế versioned offline feature table và bounded backfill ở Mốc 6. |
| 2026-11-10 | Hoàn thành Mốc 6: versioned daily Parquet, run manifest, source checksum, bounded backfill và idempotency/no-duplicate tests. | Materialize full feature table v1 rồi xây temporal training dataset ở Mốc 7. |

Khi hoàn thành một mốc, thêm một dòng mới vào bảng này. Không xóa lịch sử cũ.
