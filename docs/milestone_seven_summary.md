# Tổng kết Mốc 7 — Training dataset và baseline model

## Phạm vi đã hoàn thành

Mốc 7 đã hoàn thành temporal split, train-only preprocessing, model-ready dataset, hai model
CatBoost, đánh giá held-out test, phân tích theo entity-resolution level và manifest tái lập.

## So sánh theo entity-resolution level

### Validation

| Entity group | Rows | Fraud rate | Raw ROC-AUC | PIT ROC-AUC | Raw PR-AUC | PIT PR-AUC |
|---|---:|---:|---:|---:|---:|---:|
| `card_address` | 77.985 | 2,40% | 0,819184 | **0,834406** | 0,222941 | **0,257521** |
| `card_only` | 8.687 | 12,42% | 0,811702 | **0,814461** | 0,429548 | **0,436188** |

### Internal test

| Entity group | Rows | Fraud rate | Raw ROC-AUC | PIT ROC-AUC | Raw PR-AUC | PIT PR-AUC |
|---|---:|---:|---:|---:|---:|---:|
| `card_address` | 79.948 | 2,28% | 0,757890 | **0,782982** | 0,166981 | **0,194095** |
| `card_only` | 9.378 | 13,74% | **0,747069** | 0,744806 | 0,324159 | **0,327492** |

PIT cải thiện rõ ở primary `card_address`. Trong fallback `card_only`, test ROC-AUC giảm nhẹ
0,00226 dù PR-AUC tăng 0,00333. Nhóm này có fraud rate cao hơn rất nhiều và chỉ có entity
coarse `card1`; đây là tín hiệu cần audit ở Mốc 8, không phải lý do thay đổi model sau khi đã
mở internal test.

## Reproducibility manifest

```text
reports/generated/milestone_seven/v1/
  model_comparison.json
  reproducibility_manifest.json
```

Manifest lưu:

- SHA-256 và semantic fingerprint của training dataset;
- preprocessing artifact;
- model manifest, model run ID và checksum hai model;
- evaluation run ID, report và prediction checksums;
- SHA-256 của 13 contract/implementation files;
- Python, CatBoost, DuckDB, NumPy, Pandas, PyArrow và scikit-learn versions.

Nhờ đó có thể xác minh artifact có đúng là output của cùng dataset, code, config và model đã
được báo cáo hay không. Manifest không thay thế việc lưu raw data; nó là dấu vân tay để phát
hiện bất kỳ input/artifact nào bị thay đổi.

## Cách chạy

Mở PowerShell:

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"
python -c "import sys; print(sys.executable)"
python -m pip install -e ".[dev]"
python pipelines/complete_milestone_seven.py
```

Theo dõi đến khi thấy:

```text
[milestone-7] success: reports\generated\milestone_seven\v1
```

Release v1 đã tồn tại trên máy hiện tại và là immutable; chạy lại cùng version sẽ bị từ chối.
