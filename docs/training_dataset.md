# Model training dataset v1

## Mục tiêu

Tạo một dataset model-ready bằng cách join labeled Silver transactions với 20 offline PIT
features, áp dụng temporal split và preprocessing mà không dùng validation/internal test để
fit bất kỳ thống kê nào.

## Luồng xử lý

```text
Silver labeled transactions (590.540 rows)
        LEFT JOIN TransactionID
Offline PIT feature table v1
        ↓
One-to-one join quality checks
        ↓
Gắn model_split bằng fixed TransactionDT boundaries
        ↓
Áp dụng raw preprocessing artifact v1
        ↓
Fit nullable PIT medians chỉ trên model_split=train
        ↓
Thêm PIT missing indicators
        ↓
Ghi Parquet partition theo model_split + manifest
```

## Input và output

Input:

- `data/silver/transactions/dataset_split=train/**/*.parquet`;
- `data/offline_store/transaction_features/v1/observation_date=*/*.parquet`;
- temporal split config v1;
- preprocessing artifact v1;
- hai Feature Registries v1.

Output:

```text
data/training/model_dataset/v1/
  model_split=train/part_0.parquet
  model_split=validation/part_0.parquet
  model_split=internal_test/part_0.parquet
  manifests/<run_id>.json
```

## Feature schema

Dataset có 55 model features:

- 15 raw features: một numeric và 14 categorical;
- 20 PIT historical features;
- 20 PIT missing indicators có hậu tố `__missing`.

Ngoài ra có ID, time, label, `model_split` và bốn version columns. Tổng schema là 64 cột.

## Preprocessing

Raw preprocessing sử dụng artifact đã fit trên train:

- `TransactionAmt` null được fill bằng train median `68.95`;
- categorical null thành `__MISSING__`;
- categorical mới/hiếm thành `__UNKNOWN__`;
- validation/internal test không mở rộng vocabulary.

PIT null policy:

- count, sum và distinct-count null được fill `0`;
- average, maximum và recency null được fill bằng median tính trên train rows;
- mỗi PIT feature có thêm cột `feature_name__missing` để model phân biệt giá trị thật với
  giá trị được impute.

Ví dụ train-only medians:

| PIT feature | Fill value |
|---|---:|
| `card_addr_amount_avg_24h` | 100,0 |
| `card_addr_amount_max_7d` | 300,0 |
| `card_addr_seconds_since_previous_txn` | 44.661 giây |
| `card_amount_avg_24h` | 103,6825 |
| `card_amount_max_7d` | 554,0 |
| `card_seconds_since_previous_txn` | 5.414 giây |

Không dùng validation/internal-test values để tính các median này.

## Kết quả materialization

| Split | Rows | Fraud count | Fraud rate | TransactionDT range |
|---|---:|---:|---:|---:|
| Train | 414.542 | 14.600 | 3,5220% | 86.400–10.454.392 |
| Validation | 86.672 | 2.949 | 3,4025% | 10.454.414–13.132.788 |
| Internal test | 89.326 | 3.114 | 3,4861% | 13.132.810–15.811.131 |

Quality evidence:

```text
source rows                  = 590.540
output rows                  = 590.540
unique TransactionID         = 590.540
duplicate TransactionID      = 0
missing offline feature rows = 0
null model feature values    = 0
Parquet files                = 3
```

## Cách chạy và theo dõi

```powershell
python pipelines/build_training_dataset.py
```

Theo dõi năm stage và chỉ coi thành công khi thấy:

```text
[training-dataset] success: data\training\model_dataset\v1
```

Version là immutable; command từ chối ghi đè `v1`. Manifest lưu source paths/versions,
preprocessing semantic hash, split metrics, PIT fill values, output semantic fingerprint
và dataset SHA-256.
