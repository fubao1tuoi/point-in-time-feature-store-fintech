# POINT-IN-TIME CORRECT FEATURE STORE

Historical features đúng thời gian cho phát hiện gian lận giao dịch

IEEE-CIS Fraud Detection · Project 5 tuần

---

## 1. Bài toán

- Mô hình fraud cần biết hành vi lịch sử trước mỗi giao dịch.
- Feature sai nếu sử dụng current event hoặc giao dịch tương lai.
- Training và prediction phải nhìn thấy cùng loại thông tin.

```text
08:00 history  → được dùng
10:00 predict  → không tự tính chính nó
11:00 future   → không được dùng
```

---

## 2. Mục tiêu

- Xây pipeline từ raw data đến offline feature store.
- Tạo historical features đúng tại `prediction_time`.
- Quản lý version, lineage và checksum.
- Hỗ trợ backfill an toàn.
- Tái tạo training dataset và kết quả mô hình.

---

## 3. Dữ liệu và entity

- IEEE-CIS: 590.540 train transactions có label.
- Dataset không có customer/account ID thật.
- Primary entity: `card1 + addr1`.
- Secondary entity: `card1`.
- Model nhận cả hai views để cân bằng độ cụ thể và coverage.

---

## 4. Kiến trúc local

```text
CSV → Bronze → Silver → Observation
                         ↓
                  PIT feature engine
                         ↓
              Offline feature store v1
                         ↓
                Training dataset v1
                         ↓
              CatBoost + evaluation
```

---

## 5. Quy tắc PIT

```text
(history.event_time, history.TransactionID)
    <
(prediction_time, observation.TransactionID)
```

- Loại future event.
- Loại current event.
- Xử lý ổn định các giao dịch cùng timestamp.
- Window start inclusive, observation cutoff strict.

---

## 6. Hai mươi PIT features

Mỗi entity view có 10 feature:

- Transaction count: 1h, 24h, 7d.
- Amount sum: 1h, 24h, 7d.
- Amount average 24h và maximum 7d.
- Seconds since previous transaction.
- Distinct product count 7d.

Tổng cộng: 10 logical features × 2 entity views = 20 outputs.

---

## 7. Offline store và backfill

- Parquet partition theo `observation_date` UTC.
- Feature table và contract có version.
- Manifest lưu checksum, row count và cutoff.
- Backfill chỉ thay đúng ngày cần tính lại.
- Staging + validation + backup + rollback.

---

## 8. Training và mô hình

```text
70% quá khứ → train
15% tiếp theo → validation
15% mới nhất → internal test
```

- 15 raw features.
- 20 PIT features.
- 20 missing indicators.
- CatBoost xử lý tốt categorical features và class imbalance.

---

## 9. Kết quả internal test

- ROC-AUC: `0,815880 → 0,829082`.
- PR-AUC: `0,236695 → 0,254277`.
- Precision@100: `74% → 83%`.
- Precision@1.000: `43,7% → 45,3%`.

PIT features cung cấp thêm tín hiệu; mục tiêu chính vẫn là correctness của platform.

---

## 10. Bằng chứng correctness

- Golden dataset tính tay: 200 expected feature values.
- Future-event invariance.
- Boundary và same-time tests.
- Null entity, skew và late-arrival tests.
- 17 leakage/hardening checks.
- Clean-clone dry-run tái tạo cùng row count, prediction và metric.

---

## 11. Kiến trúc Google Cloud dự kiến

```text
Cloud Storage raw
       ↓
Scheduler → Workflows → Cloud Run Jobs
       ↓
Bronze → Silver → PIT → prediction
       ↓
Cloud Storage + BigQuery
       ↓
Logging + Monitoring
```

---

## 12. Kết luận

- Hoàn thành pipeline end-to-end trên local.
- Historical features không nhìn thấy tương lai.
- Có versioning, lineage, safe backfill và reproducibility evidence.
- Raw + PIT model tốt hơn raw baseline trên internal test.
- Sẵn sàng đóng gói Docker và triển khai batch pipeline lên Google Cloud.

---

# CẢM ƠN

Demo: append giao dịch tương lai lúc 11:00 và chứng minh features của observation 10:00 không đổi.
