# Project Progress Tracker

> Đây là file theo dõi tiến độ chính của project. Sau mỗi lần hoàn thành công việc, tick `[x]`, cập nhật cột **Bằng chứng** và chuyển mục **Việc tiếp theo**. Kế hoạch chi tiết và giải thích kỹ thuật vẫn nằm trong [`PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md`](./PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md).

## 1. Trạng thái hiện tại

```text
Giai đoạn hiện tại : Tuần 1 — Data understanding và thiết kế nền tảng
Đã hoàn thành       : Dataset audit + data dictionary + entity-key analysis
Đang làm tiếp       : Bronze/Silver pipeline và canonical transaction schema
Mục tiêu gần nhất   : Tạo silver_transactions.parquet chạy lặp lại được
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
Bronze và Silver pipeline             ← BƯỚC TIẾP THEO
        ↓
Feature Registry + golden dataset
        ↓
Point-in-Time feature engine
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

- [ ] Viết cấu hình source paths và synthetic epoch.
- [ ] Viết Bronze ingestion giữ nguyên dữ liệu nguồn và metadata ingest.
- [ ] Tạo checksum manifest cho raw inputs.
- [ ] Viết Silver transformation: cast type và deduplicate có kiểm soát.
- [ ] Tạo `event_time = synthetic_epoch + TransactionDT seconds`.
- [ ] Left join transaction với identity và tạo `has_identity`.
- [ ] Thêm cả hai entity IDs và routing metadata vào Silver.
- [ ] Ghi `silver_transactions` ra Parquet, partition theo thời gian phù hợp.
- [ ] Viết data-quality tests cho row count, uniqueness, event time và left join.
- [ ] Kiểm tra chạy lại cho kết quả logic giống nhau.

**Hoàn thành khi:** có thể chạy một command để tạo canonical `silver_transactions` mà không mất transaction và tất cả quality tests pass.

### Mốc 4 — Feature Registry và golden dataset

- [x] Tạo khung YAML cho primary và secondary transaction velocity features.
- [ ] Chốt quy tắc same timestamp bằng `event_time` và `TransactionID`.
- [ ] Chốt 8–12 feature MVP cho cả hai entity views.
- [ ] Viết schema/model validate feature definitions.
- [ ] Viết `docs/feature_catalog.md`.
- [ ] Tạo golden dataset nhỏ bằng tay.
- [ ] Tạo expected result cho no-history, boundary, same-time, null entity và future event.

**Hoàn thành khi:** YAML sai bị từ chối tự động và expected values của golden dataset được review bằng tay.

### Mốc 5 — Point-in-Time feature computation

- [ ] Dùng mỗi transaction làm observation tại `prediction_time = event_time`.
- [ ] Tính `card_addr_*` theo primary entity.
- [ ] Tính `card_*` theo secondary entity.
- [ ] Chỉ dùng lịch sử thỏa `history_time < prediction_time`.
- [ ] Xử lý đúng window boundary và same timestamp.
- [ ] Giữ observation không có history bằng left PIT join.
- [ ] Viết golden tests và append-only invariance test.
- [ ] Chứng minh thêm future rows không làm đổi feature của past rows.

**Hoàn thành khi:** golden tests pass 100%, số output bằng số observations và không có cutoff violation.

### Mốc 6 — Offline feature store và backfill

- [ ] Materialize feature table có version ra Parquet.
- [ ] Partition theo observation date/time range.
- [ ] Lưu run ID, source checksum, feature version, row count và cutoff range.
- [ ] Viết backfill command nhận `start_time` và `end_time`.
- [ ] Kiểm tra backfill idempotent, không tạo duplicate.

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

Chỉ tập trung vào **Mốc 3 — Bronze/Silver data foundation**, theo thứ tự:

1. Tạo `configs/sources.yaml` và chốt synthetic epoch.
2. Viết ingestion tạo Bronze Parquet cùng checksum/metadata.
3. Viết transformation tạo `silver_transactions`.
4. Gắn `event_time`, identity, hai entity IDs và routing metadata.
5. Viết data-quality tests và chạy trên dữ liệu thật.

Không bắt đầu PIT engine trước khi canonical Silver dataset và event-time contract ổn định.

## 5. Nhật ký cập nhật

| Ngày | Thay đổi | Bước tiếp theo |
|---|---|---|
| 2026-11-03 | Hoàn thành profiling, data dictionary và chốt primary/secondary entities cho MVP. | Xây Bronze/Silver pipeline. |
| 2026-11-03 | Bổ sung streaming SHA-256 và `raw_checksums.json` cho raw inputs. | Xây Bronze ingestion và lưu checksum vào metadata. |

Khi hoàn thành một mốc, thêm một dòng mới vào bảng này. Không xóa lịch sử cũ.
