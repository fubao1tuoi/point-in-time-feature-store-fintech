# Point-in-Time Correct Feature Store for Fintech

Data Engineering project xây dựng một Point-in-Time Correct Feature Store phục vụ bài toán phát hiện gian lận trên bộ dữ liệu IEEE-CIS Fraud Detection.

## Mục tiêu

- Tạo feature lịch sử mà không sử dụng dữ liệu tương lai.
- Materialize feature vào offline store có version.
- Sinh training dataset có thể tái lập bằng Point-in-Time Join.
- Hỗ trợ backfill idempotent và kiểm tra data leakage.
- Đánh giá hiệu năng của partition pruning và các tối ưu PIT pipeline.

## Dataset

Nguồn dữ liệu: [IEEE-CIS Fraud Detection](https://www.kaggle.com/competitions/ieee-fraud-detection/data).

Dataset không được lưu trong Git repository. Sau khi tải, đặt các file CSV trong `data/raw/`.

Các file đầu vào dự kiến:

```text
data/raw/train_transaction.csv
data/raw/train_identity.csv
data/raw/test_transaction.csv
data/raw/test_identity.csv
```

## Trạng thái

Project đang ở giai đoạn khởi tạo và khảo sát dữ liệu.

## Cấu trúc

```text
configs/        Cấu hình nguồn dữ liệu, project và feature definitions
data/           Dữ liệu local; chỉ sample nhỏ và .gitkeep được commit
docs/           Kiến trúc, data contract, feature catalog và runbook
notebooks/      Notebook dùng cho khảo sát, không chứa production logic
pipelines/      Entry points cho các pipeline end-to-end
reports/        Báo cáo profiling, benchmark và kết quả kiểm thử
src/            Source code chính
tests/          Unit, integration, data-quality và PIT correctness tests
```

## Thiết lập môi trường

Yêu cầu Python 3.11 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Sao chép cấu hình môi trường mẫu:

```powershell
Copy-Item .env.example .env
```

## Kiểm tra project

```powershell
pytest
```

## Tài liệu

- [Project outline](PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md)
- [Lý thuyết Point-in-Time Correct Feature Store](LY_THUYET_POINT_IN_TIME_CORRECT_FEATURE_STORE.md)
- [Tài liệu trong docs](docs/README.md)

## Nguyên tắc dữ liệu

- Không commit dataset, Kaggle credential, `.env`, model artifact hoặc runtime volume.
- Đánh giá chính sử dụng chronological split, không dùng random split.
- Mọi feature lịch sử phải thỏa điều kiện cutoff được khai báo trong feature definition.

