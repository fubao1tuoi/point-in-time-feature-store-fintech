# Đánh giá raw baseline và raw + PIT MVP

## Mục tiêu

Đánh giá hai model trên cùng validation và internal-test periods bằng các ranking metrics phù
hợp với fraud detection. Internal test chỉ được mở trong pipeline này, sau khi model và best
iteration đã được khóa.

## Ý nghĩa metric

- **ROC-AUC:** khả năng xếp một fraud cao hơn một giao dịch hợp lệ trên toàn bộ thresholds.
- **PR-AUC:** dùng Average Precision, tập trung hơn vào class fraud hiếm; baseline ngẫu nhiên
  xấp xỉ fraud rate khoảng 3,4–3,5%.
- **Recall@FPR:** phần trăm fraud tìm được trong khi tỷ lệ giao dịch hợp lệ bị cảnh báo nhầm
  không vượt mức FPR cấu hình.
- **Precision@K:** trong K giao dịch có fraud probability cao nhất, bao nhiêu phần trăm thực sự
  là fraud.

## Kết quả tổng quan

| Split | Model | ROC-AUC | PR-AUC |
|---|---|---:|---:|
| Validation | Raw | 0,849364 | 0,304732 |
| Validation | Raw + PIT | **0,860614** | **0,329254** |
| Internal test | Raw | 0,815880 | 0,236695 |
| Internal test | Raw + PIT | **0,829082** | **0,254277** |

Trên internal test chưa từng dùng khi train, PIT tăng ROC-AUC khoảng `0,01320` và PR-AUC
khoảng `0,01758`.

## Recall tại giới hạn false-positive rate

| Split | Model | FPR ≤ 0,1% | FPR ≤ 1% | FPR ≤ 5% |
|---|---|---:|---:|---:|
| Validation | Raw | 7,12% | 23,43% | 47,51% |
| Validation | Raw + PIT | **8,27%** | **25,87%** | **49,71%** |
| Internal test | Raw | 4,66% | 17,12% | **41,49%** |
| Internal test | Raw + PIT | **5,94%** | **18,11%** | 41,07% |

PIT tốt hơn ở các mức FPR chặt 0,1% và 1%. Tại FPR 5% trên internal test, raw model cao hơn
nhẹ khoảng 0,42 điểm phần trăm; vì vậy không nên kết luận PIT thắng ở mọi operating point.

## Precision trong nhóm ưu tiên điều tra

| Split | Model | Top 100 | Top 1.000 | Top 1% |
|---|---|---:|---:|---:|
| Validation | Raw | 81,0% | 51,9% | 53,40% |
| Validation | Raw + PIT | **94,0%** | **54,6%** | **56,98%** |
| Internal test | Raw | 74,0% | 43,7% | 44,74% |
| Internal test | Raw + PIT | **83,0%** | **45,3%** | **46,87%** |

Ví dụ trên internal test, nếu đội fraud chỉ kiểm tra 100 giao dịch có score cao nhất, model
PIT đưa 83 fraud thật vào danh sách, so với 74 của raw baseline.

## Output kiểm chứng

```text
reports/generated/model_evaluation/v1/
  evaluation_report.json
  predictions/
    validation.parquet
    internal_test.parquet
```

JSON chứa toàn bộ metric, observed FPR và score threshold. Hai file prediction giữ
`TransactionID`, label thật, entity-resolution group và xác suất fraud của cả hai model để
có thể audit hoặc tính lại metric.

## Cách chạy và theo dõi

Mở PowerShell rồi chạy đủ các bước:

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"
python -c "import sys; print(sys.executable)"
python -m pip install -e ".[dev]"
python pipelines/evaluate_baseline_models.py
```

Python executable phải là:

```text
D:\AITC VinUni\Fintech project\.venv\Scripts\python.exe
```

Theo dõi đến khi xuất hiện:

```text
[model-evaluation] success: reports\generated\model_evaluation\v1
```

Evaluation v1 là immutable. Trên máy hiện tại v1 đã tồn tại; chạy lại cùng version sẽ bị từ
chối để tránh ghi đè bằng kết quả khác.
