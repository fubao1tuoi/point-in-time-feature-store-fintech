# Training raw baseline và raw + PIT MVP

## Mục tiêu

Hai model được train để kiểm tra câu hỏi chính: khi giữ nguyên thuật toán, dữ liệu và cách
chia thời gian, 20 historical PIT features có cung cấp thêm tín hiệu so với raw transaction
features hay không.

## Hai model

| Model | Đầu vào | Số feature |
|---|---|---:|
| `raw_baseline` | 15 raw features đã preprocess | 15 |
| `raw_plus_pit_mvp` | 15 raw + 20 PIT + 20 PIT missing indicators | 55 |

Model MVP nhận cả hai entity views: 10 cột `card_addr_*` của primary entity và 10 cột
`card_*` của secondary entity. Missing indicators không phải historical calculation mới;
chúng cho model biết PIT value tương ứng là dữ liệu thật hay giá trị đã được điền.

## Vì sao dùng CatBoost

Raw data có nhiều categorical columns như card, email và device. CatBoost có thể xử lý
categorical values trực tiếp, tránh one-hot encoding tạo ra ma trận rất rộng. Cùng một cấu
hình CatBoost, seed và temporal split được dùng cho cả hai model để phép so sánh công bằng.

## Luồng train không leakage

```text
training dataset v1
    ├── train (414.542 rows)      -> fit model
    ├── validation (86.672 rows)  -> early stopping/chọn iteration
    └── internal_test             -> KHÔNG đọc khi train
```

Internal test được giữ kín cho bước đánh giá cuối. Pipeline kiểm tra dataset version, schema,
feature contracts và chỉ nạp hai split `train`, `validation`.

## Kết quả train v1

| Model | Best iteration | Validation ROC-AUC |
|---|---:|---:|
| Raw baseline | 140 | 0,849364 |
| Raw + PIT MVP | 296 | 0,860614 |

MVP cao hơn raw baseline khoảng **0,01125 AUC point** trên validation. Đây mới là tín hiệu
ban đầu rằng PIT features hữu ích; kết luận cuối phải dựa trên các metric đầy đủ và internal
test ở task tiếp theo.

## Artifact

Output local, được `.gitignore` bảo vệ:

```text
models/fraud_detection/v1/
  raw_baseline.cbm
  raw_plus_pit_mvp.cbm
  raw_baseline_feature_importance.csv
  raw_plus_pit_mvp_feature_importance.csv
  model_manifest.json
```

Manifest lưu feature list, hyperparameters, random seed, số dòng đã dùng, best iteration,
validation score và SHA-256 của từng model. `internal_test_used=false` là bằng chứng split
cuối chưa tham gia train.

## Cách chạy và theo dõi

Mở PowerShell, chuyển vào đúng project và bật virtual environment:

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"
```

Kiểm tra Python đang dùng phải nằm trong `.venv` của project:

```powershell
python -c "import sys; print(sys.executable)"
```

Kết quả mong đợi:

```text
D:\AITC VinUni\Fintech project\.venv\Scripts\python.exe
```

Nếu chưa cài dependency mới, chạy một lần:

```powershell
python -m pip install -e ".[dev]"
```

Sau đó train cả hai model:

```powershell
python pipelines/train_baseline_models.py
```

Theo dõi các dòng:

```text
[1/4] validating contracts and loading train/validation only
[2/4] training raw_baseline (1/2): features=15
[2/4] training raw_plus_pit_mvp (2/2): features=55
[model-training] success: models\fraud_detection\v1
```

CatBoost in AUC mỗi 25 iterations. Chỉ coi run thành công khi có dòng cuối. Model bundle v1
là immutable; muốn train lại phải dùng version mới, không ghi đè artifact đã dùng.
