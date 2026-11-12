# Train-only preprocessing policy v1

## Mục tiêu

Fit mọi thống kê preprocessing chỉ bằng temporal train period. Validation và internal test
chỉ được transform bằng artifact đã khóa; không được tham gia tính median hoặc category
vocabulary.

## Phạm vi v1

Artifact v1 phục vụ raw-feature baseline với các trường dễ giải thích:

- Numeric: `TransactionAmt`.
- Categorical: `ProductCD`, `card1`–`card6`, `addr1`, `addr2`, purchaser/recipient email,
  device fields và `entity_resolution_level`.

Không dùng `TransactionID`, `TransactionDT`, `isFraud`, entity IDs hoặc metadata làm model
features. Hai mươi PIT features sẽ được join ở task training-dataset; no-history semantics
của chúng đã được Feature Registry khóa. Nếu model cần learned imputation cho nullable PIT
features, artifact raw+PIT kế tiếp phải dùng cùng train-only fit boundary.

## Fit boundary

```text
TransactionDT < 10.454.400
fit rows = 414.542
validation/test rows used for fit = 0
```

`TransactionAmt` dùng median train. Giá trị hiện tại là `68.95`; validation/test amount
không được tham gia tính con số này.

Categorical vocabulary chỉ giữ category xuất hiện ít nhất 20 lần trong train:

```text
null                    -> __MISSING__
category mới hoặc hiếm  -> __UNKNOWN__
category đã học         -> giữ category cố định
```

Validation/test không được mở rộng vocabulary. Điều này mô phỏng production: model có thể
gặp category chưa từng xuất hiện khi fit.

## Artifact và audit report

Chạy:

```powershell
python pipelines/fit_preprocessor.py
```

Output local:

```text
artifacts/preprocessing/v1/preprocessor.json
reports/generated/preprocessing_fit_report.json
```

Artifact lưu median, vocabulary, fit range, row count và semantic SHA-256. Report lưu số
unknown categories theo train/validation/internal test và xác nhận không có row ngoài train
tham gia fit. Cả hai là generated runtime artifacts và bị `.gitignore`; config/code/docs
được commit để tái tạo chúng.

## Tại sao cần quy tắc này?

Nếu median hoặc vocabulary được học từ validation/test, pipeline đã dùng thông tin của
tương lai trước khi đánh giá. Dù không đọc `isFraud`, đó vẫn là preprocessing leakage và
metric có thể lạc quan hơn production.
