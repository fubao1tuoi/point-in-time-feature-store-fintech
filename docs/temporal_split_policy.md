# Temporal split policy v1

## Mục tiêu

Chia 590.540 labeled IEEE-CIS train transactions thành train, validation và internal test
theo thứ tự thời gian. Không random split vì model triển khai thực tế luôn học từ quá khứ
và dự đoán các giao dịch xảy ra sau đó.

## Chính sách đã chốt

Source chỉ gồm `dataset_split=train`, vì Kaggle test không có `isFraud`. Trục chia là
`TransactionDT`; `event_time` tương đương nhưng chỉ là synthetic timestamp được derive từ
cùng offset này.

| Model split | Điều kiện `TransactionDT` | Rows | Tỷ lệ | Fraud rate |
|---|---:|---:|---:|---:|
| Train | `< 10.454.400` | 414.542 | 70,20% | 3,5220% |
| Validation | `>= 10.454.400` và `< 13.132.800` | 86.672 | 14,68% | 3,4025% |
| Internal test | `>= 13.132.800` | 89.326 | 15,13% | 3,4861% |

Synthetic references để dễ đọc:

- Validation bắt đầu: `2017-05-02T00:00:00Z`.
- Internal test bắt đầu: `2017-06-02T00:00:00Z`.

Đây không phải ngày giao dịch thật. Chúng được tính từ synthetic epoch cố định cộng
`TransactionDT` giây.

## Boundary semantics

Các interval dùng start-inclusive/end-exclusive. Transaction đúng boundary được đưa vào
period phía sau:

```text
TransactionDT = 10.454.400 -> validation
TransactionDT = 13.132.800 -> internal_test
```

Nhờ đó không có một transaction thuộc hai splits. Hai boundary được làm tròn về UTC
midnight gần nhất sau khi xác định quantile 70%/85%. Vì vậy một `observation_date` không bị
chia giữa hai model splits. Config lưu fixed boundaries thay vì tính lại quantile mỗi run;
nếu data mới được append, transaction cũ không tự chuyển sang split khác.

Config đặt `boundary_alignment_seconds: 86400`; validator từ chối mọi boundary không chia
hết cho số giây trong một ngày. Với synthetic epoch ở UTC midnight, điều này bảo đảm split
luôn bắt đầu đúng `00:00:00Z`.

## Vai trò từng split

- **Train:** fit model, encoder, imputer và mọi statistics học từ dữ liệu.
- **Validation:** chọn feature, threshold và hyperparameter; không fit preprocessing.
- **Internal test:** chỉ đánh giá cuối sau khi quyết định đã chốt bằng validation.

Kaggle test không thay thế internal test vì không có label công khai để tự đánh giá.

## Automated audit

Chạy:

```powershell
python pipelines/analyze_temporal_split.py
```

Report runtime được ghi tại `reports/generated/temporal_split_report.json` và kiểm tra:

- `TransactionID`, `TransactionDT`, `isFraud` hợp lệ;
- không duplicate `TransactionID`;
- tổng rows của ba splits bằng source rows;
- cả ba period đều tồn tại và có fraud examples;
- `max(train) < min(validation)`;
- `max(validation) < min(internal_test)`.
