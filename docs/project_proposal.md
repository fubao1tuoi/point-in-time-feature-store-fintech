# Project Proposal

## 1. Tên đề tài

Point-in-Time Correct Feature Store for Fintech Fraud Detection

## 2. Bài toán

Xây dựng một Feature Store tạo ra các feature lịch sử cho mỗi giao
dịch mà không sử dụng dữ liệu xảy ra sau thời điểm cần dự đoán.

## 3. Vấn đề cần giải quyết

Pipeline ML thông thường có thể vô tình sử dụng dữ liệu tương lai,
gây data leakage và làm kết quả đánh giá offline cao không thực tế.

Project áp dụng Point-in-Time Join để bảo đảm feature dùng cho một
giao dịch tại thời điểm T chỉ được tạo từ dữ liệu tồn tại trước T.

## 4. Dataset

IEEE-CIS Fraud Detection, gồm:

- Transaction data.
- Identity/device data.
- TransactionDT biểu diễn thời gian tương đối.
- isFraud là nhãn phân loại.
- TransactionID dùng để nối transaction và identity.

## 5. Input

- train_transaction.csv
- train_identity.csv
- test_transaction.csv
- test_identity.csv

## 6. Output mong đợi

- Canonical transaction dataset.
- Versioned feature definitions.
- Point-in-time correct offline feature table.
- Reproducible training dataset.
- Automated leakage tests.
- Baseline fraud model.
- Performance benchmark.

## 7. Phạm vi MVP

- Batch ingestion.
- Bronze và Silver data layer.
- Surrogate entity key.
- Point-in-Time feature computation.
- Offline feature store.
- Chronological split.
- Baseline model.
- PIT correctness tests.

## 8. Ngoài phạm vi bắt buộc

- Production streaming system.
- Kubernetes.
- Deep-learning model phức tạp.
- Tối ưu Kaggle leaderboard.
- Customer identity resolution chính xác.

## 9. Tiêu chí thành công

- Không có feature event xảy ra sau prediction time.
- Pipeline có thể chạy lại và tái tạo kết quả.
- Training dataset được chia theo thời gian.
- Có ít nhất 8 feature lịch sử.
- Có benchmark và demo rõ ràng.