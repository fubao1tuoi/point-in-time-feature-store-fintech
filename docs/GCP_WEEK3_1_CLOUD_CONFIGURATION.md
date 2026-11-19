# Tuần 3.1 — Tạo Google Cloud project và chuẩn hóa cloud configuration

## 1. Mục tiêu

Sau hướng dẫn này, mày sẽ có:

- một Google Cloud project riêng cho project PIT Feature Store;
- một Cloud Billing account đã liên kết với project;
- một budget alert để theo dõi chi phí;
- Google Cloud CLI hoạt động trên Windows;
- project và region mặc định trong `gcloud`;
- bucket name dự kiến, chưa tạo bucket;
- bốn environment variables cho cloud config;
- cloud config được validator xác nhận;
- tests và Ruff của task 3.1 đều pass.

Task này chưa tạo Cloud Storage bucket, Artifact Registry, Cloud Run Job hoặc Workflows. Các
tài nguyên đó sẽ được Terraform tạo ở bước infrastructure sau khi config đã chốt.

## 2. Những gì đã có trong source code

```text
configs/cloud/dev.yaml
src/pit_feature_store/cloud_configuration.py
src/pit_feature_store/structured_logging.py
pipelines/validate_cloud_config.py
tests/unit/test_cloud_configuration.py
tests/unit/test_structured_logging.py
```

Config không chứa password, payment information, access token hoặc service-account key. Nó
chỉ tham chiếu bốn biến:

```text
GCP_PROJECT_ID
GCP_REGION
GCP_DATA_BUCKET
PIT_DATA_ROOT
```

---

# PHẦN A — Tạo tài khoản, billing và Google Cloud project

## 3. Đăng nhập Google Cloud Console

Mở trình duyệt và truy cập:

[https://console.cloud.google.com/](https://console.cloud.google.com/)

Đăng nhập bằng Google account mà mày muốn dùng cho project.

Nếu đây là tài khoản công ty/trường học:

- kiểm tra organization policy;
- hỏi quản trị viên nếu không có quyền tạo project hoặc liên kết billing;
- không dùng thẻ cá nhân nếu tổ chức yêu cầu billing tập trung.

Nếu là tài khoản cá nhân, project thường nằm dưới `No organization`.

## 4. Tạo hoặc kiểm tra Cloud Billing account

Google Cloud project là nơi chứa tài nguyên. Cloud Billing account là nơi ghi nhận và thanh
toán chi phí. Muốn chạy Cloud Run hoặc tạo phần lớn tài nguyên, project phải liên kết với một
billing account đang hoạt động, kể cả khi dịch vụ có free tier.

### Trường hợp đã có billing account

Trong Google Cloud Console:

```text
Navigation menu
→ Billing
→ Manage billing accounts
```

Kiểm tra billing account có trạng thái hoạt động và mày có quyền sử dụng nó.

### Trường hợp chưa có billing account

Trong Console:

```text
Navigation menu
→ Billing
→ Manage billing accounts
→ Create account
```

Mày sẽ cần tự nhập:

- tên billing account;
- quốc gia;
- payments profile;
- phương thức thanh toán nếu Google yêu cầu.

Không đưa thông tin thẻ, hóa đơn hoặc payment profile vào repository, `.env`, ảnh chụp gửi cho
người khác hoặc nội dung trao đổi với AI.

Tài liệu chính thức:
[Create a Cloud Billing account](https://docs.cloud.google.com/billing/docs/how-to/create-billing-account).

## 5. Tạo Google Cloud project bằng Console

Đây là cách dễ kiểm soát nhất cho lần đầu.

### Bước 5.1 — Mở màn hình tạo project

Trong thanh trên cùng của Google Cloud Console:

```text
Project selector
→ New Project
```

Hoặc mở trang quản lý resource rồi chọn `Create Project`.

### Bước 5.2 — Điền Project name

Gợi ý:

```text
PIT Feature Store Dev
```

Project name chỉ là tên hiển thị, có thể có khoảng trắng.

### Bước 5.3 — Chọn Project ID

Gợi ý cấu trúc:

```text
pit-feature-store-dev-<chuỗi-ngắn-duy-nhất>
```

Ví dụ:

```text
pit-feature-store-dev-tvn01
```

Không copy nguyên ví dụ nếu Google báo đã tồn tại. Project ID:

- phải duy nhất trên toàn Google Cloud;
- dùng chữ thường, số và dấu `-`;
- không có khoảng trắng;
- nên dài 6–30 ký tự;
- gần như được xem là định danh cố định sau khi tạo.

Ghi lại chính xác `Project ID`. Các bước sau không dùng Project name.

### Bước 5.4 — Chọn Location

Nếu dùng tài khoản cá nhân, thường chọn:

```text
No organization
```

Nếu dùng organization, chọn đúng organization/folder theo quy định của đơn vị.

### Bước 5.5 — Tạo project

Chọn `Create`, chờ Google tạo xong, rồi dùng Project selector để chuyển sang project mới.

Tài liệu chính thức:
[Create and manage projects](https://docs.cloud.google.com/resource-manager/docs/creating-managing-projects).

## 6. Liên kết project với billing account

Chọn đúng project vừa tạo ở thanh trên cùng, sau đó:

```text
Navigation menu
→ Billing
```

Nếu Console hiển thị `Link a billing account`:

```text
Link a billing account
→ chọn billing account đang hoạt động
→ Set account
```

Nếu project đã được liên kết tự động, kiểm tra tên billing account đang dùng.

Nếu không chọn được billing account, mày có thể thiếu:

- quyền Owner hoặc Project Billing Manager trên project;
- quyền Billing Account User/Administrator trên billing account.

Tài liệu chính thức:
[Enable or change billing for a project](https://docs.cloud.google.com/billing/docs/how-to/modify-project).

## 7. Tạo budget alert trước khi tạo tài nguyên

Budget alert giúp phát hiện chi phí sớm. Nó thường là cảnh báo, không phải hard spending cap và
không tự động tắt tài nguyên khi vượt ngân sách.

Trong Console, khi đang chọn đúng project:

```text
Navigation menu
→ Billing
→ Budgets & alerts
→ Create budget
```

### Bước 7.1 — Name và scope

Gợi ý tên:

```text
pit-feature-store-dev-monthly
```

Scope chỉ chọn project PIT Feature Store, không chọn toàn bộ billing account nếu billing account
còn phục vụ project khác.

### Bước 7.2 — Budget amount

Nhập mức chi phí thử nghiệm tối đa mày có thể chấp nhận trong một tháng. Không có một con số
chung phù hợp cho mọi tài khoản hoặc loại tiền tệ.

Ví dụ cách suy nghĩ:

```text
Ngân sách học tập/thử nghiệm của cá nhân
→ chọn một mức nhỏ mà mày sẵn sàng chi trả
→ tăng sau khi đã có cost baseline
```

### Bước 7.3 — Alert thresholds

Có thể đặt:

```text
50% actual spend
80% actual spend
100% actual spend
```

Google mặc định thường đề xuất 50%, 90% và 100%; mày có thể đổi 90% thành 80% để được cảnh báo
sớm hơn.

Chọn gửi email cho project owner hoặc email mà mày theo dõi thường xuyên, rồi chọn `Finish`.

Tài liệu chính thức:
[Create budgets and budget alerts](https://docs.cloud.google.com/billing/docs/how-to/budgets).

## 8. Kiểm tra lại trên Console

Trước khi chuyển sang CLI, xác nhận:

```text
[x] Project selector đang chọn đúng project mới
[x] Project ID đã được ghi lại
[x] Billing account đã liên kết
[x] Budget alert đã tồn tại
[x] Không có tài nguyên compute nào đang chạy
```

---

# PHẦN B — Cài và cấu hình Google Cloud CLI trên Windows

## 9. Kiểm tra `gcloud`

Mở PowerShell mới:

```powershell
gcloud --version
```

Nếu có kết quả phiên bản, chuyển sang mục 11.

## 10. Cài Google Cloud CLI nếu chưa có

Cách an toàn nhất là tải Windows installer từ tài liệu chính thức:

[Install the Google Cloud CLI](https://docs.cloud.google.com/sdk/docs/install-sdk)

Trong installer:

- giữ lựa chọn cài bundled Python nếu không có lý do đặc biệt để đổi;
- cho phép thêm `gcloud` vào `PATH`;
- hoàn tất cài đặt;
- đóng toàn bộ PowerShell cũ và mở PowerShell mới.

Kiểm tra lại:

```powershell
gcloud --version
```

Google Cloud CLI có Python riêng; nó không thay thế `.venv` của project.

## 11. Khởi tạo và đăng nhập CLI

Chạy:

```powershell
gcloud init
```

Lệnh sẽ:

1. yêu cầu đăng nhập hoặc chọn account;
2. mở trình duyệt xác thực;
3. cho chọn project mặc định;
4. có thể hỏi region/zone mặc định.

Chọn đúng Google account và project ID vừa tạo.

Nếu đã init từ trước nhưng cần đổi tài khoản:

```powershell
gcloud auth login
```

Không chạy rồi chia sẻ output của:

```text
gcloud auth print-access-token
```

## 12. Kiểm tra account và project hiện hành

```powershell
gcloud auth list
gcloud config get-value account
gcloud config get-value project
```

Project trả về phải đúng `Project ID`, không phải Project name.

Nếu chưa đúng:

```powershell
gcloud config set project "YOUR_PROJECT_ID"
```

Kiểm tra project tồn tại và mày có quyền đọc:

```powershell
gcloud projects describe "YOUR_PROJECT_ID"
```

## 13. Kiểm tra billing bằng CLI

```powershell
gcloud billing projects describe "YOUR_PROJECT_ID"
```

Tìm trạng thái billing được bật. Nếu command báo thiếu quyền nhưng Console đã xác nhận billing,
ghi lại lỗi quyền thay vì tự cấp thêm Owner/Billing Admin không cần thiết.

---

# PHẦN C — Chốt region và bucket name dự kiến

## 14. Chốt region

Với vị trí sử dụng hiện tại, plan đề xuất bắt đầu kiểm tra:

```text
asia-southeast1
```

Chạy:

```powershell
gcloud run regions list --filter="name:asia-southeast1"
```

Nếu có kết quả và organization không giới hạn region, dùng region này làm giá trị ban đầu.

Đặt region mặc định cho Cloud Run:

```powershell
gcloud config set run/region asia-southeast1
gcloud config get-value run/region
```

Không đặt nhiều region khác nhau cho từng service trong MVP. Khi tạo BigQuery/GCS sau này phải
kiểm tra location compatibility.

## 15. Chọn bucket name dự kiến

Chưa tạo bucket ở task 3.1. Chỉ chốt tên để config và Terraform dùng cùng một giá trị.

Gợi ý:

```text
<project-id>-pit-data-dev
```

Ví dụ:

```text
pit-feature-store-dev-tvn01-pit-data-dev
```

Bucket name cần:

- duy nhất toàn cầu;
- dài 3–63 ký tự;
- chữ thường, số, `.`, `_` hoặc `-`;
- không bắt đầu bằng `gs://`;
- không chứa thông tin cá nhân hoặc credential.

Terraform sẽ phát hiện nếu tên đã được người khác sử dụng. Nếu bị trùng, thêm một suffix ngắn
không nhạy cảm.

---

# PHẦN D — Kết nối project local với cloud configuration

## 16. Bật virtual environment của project

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"
python -c "import sys; print(sys.executable)"
```

Python phải nằm trong:

```text
D:\AITC VinUni\Fintech project\.venv\Scripts\python.exe
```

## 17. Set bốn environment variables

Thay hai giá trị `YOUR_...`:

```powershell
$env:GCP_PROJECT_ID = "YOUR_PROJECT_ID"
$env:GCP_REGION = "asia-southeast1"
$env:GCP_DATA_BUCKET = "YOUR_GLOBALLY_UNIQUE_BUCKET_NAME"
$env:PIT_DATA_ROOT = "/mnt/pit-data"
```

Ý nghĩa:

| Biến | Ví dụ | Ý nghĩa |
|---|---|---|
| `GCP_PROJECT_ID` | `pit-feature-store-dev-tvn01` | Project chứa tài nguyên |
| `GCP_REGION` | `asia-southeast1` | Region thống nhất |
| `GCP_DATA_BUCKET` | `...-pit-data-dev` | Bucket private sẽ tạo sau |
| `PIT_DATA_ROOT` | `/mnt/pit-data` | Mount/root trong Linux container |

Các biến chỉ tồn tại trong PowerShell hiện tại. Đóng terminal thì set lại.

Kiểm tra:

```powershell
Get-ChildItem `
  Env:GCP_PROJECT_ID,`
  Env:GCP_REGION,`
  Env:GCP_DATA_BUCKET,`
  Env:PIT_DATA_ROOT
```

## 18. Validate cloud configuration

```powershell
python pipelines/validate_cloud_config.py
```

Thành công khi JSON có:

```json
"stage": "cloud_config",
"status": "success",
"environment": "dev"
```

Xem effective config:

```powershell
python pipelines/validate_cloud_config.py --show-effective
```

Kiểm tra:

```text
gcp.project_id       = Project ID vừa tạo
gcp.region           = asia-southeast1 hoặc region đã chốt
gcp.data_bucket      = bucket name, không có gs://
runtime_paths.*      = đều nằm dưới /mnt/pit-data
execution.timezone   = UTC
labels.environment   = dev
```

## 19. Chạy tests của task 3.1

```powershell
python -m pytest `
  tests/unit/test_cloud_configuration.py `
  tests/unit/test_structured_logging.py
```

Kết quả mong đợi:

```text
4 passed
```

Chạy Ruff:

```powershell
python -m ruff check `
  src/pit_feature_store/cloud_configuration.py `
  src/pit_feature_store/structured_logging.py `
  pipelines/validate_cloud_config.py `
  tests/unit/test_cloud_configuration.py `
  tests/unit/test_structured_logging.py
```

Kết quả:

```text
All checks passed!
```

## 20. Structured logging contract

Các cloud jobs sau này sẽ ghi JSON một dòng:

```json
{
  "timestamp_utc": "...",
  "run_id": "daily-2017-01-08",
  "stage": "silver",
  "status": "success",
  "environment": "dev",
  "processing_date": "2017-01-08",
  "version": 1,
  "row_count": 144,
  "duration_seconds": 12.5
}
```

Không ghi raw transaction, access token hoặc secret vào `message`/`extra`.

## 21. Path contract local và cloud

Local vẫn dùng:

```text
data/raw
data/bronze
data/silver
reports/generated
```

Cloud config expand từ:

```text
PIT_DATA_ROOT=/mnt/pit-data
```

thành:

```text
/mnt/pit-data/raw
/mnt/pit-data/bronze
/mnt/pit-data/silver
/mnt/pit-data/offline
/mnt/pit-data/training
/mnt/pit-data/models
/mnt/pit-data/reports
```

Task Docker/storage adapter tiếp theo mới mount bucket và nối từng pipeline command vào contract
này. Task 3.1 chưa upload dữ liệu và chưa tạo GCP resource.

---

# PHẦN E — Checklist hoàn thành

## 22. Checklist Console và billing

- [x] Đăng nhập đúng Google account.
- [x] Có active Cloud Billing account.
- [x] Tạo project mới và ghi lại Project ID.
- [x] Project đã liên kết billing account.
- [x] Tạo budget alert scoped đúng project.
- [x] Hiểu rằng budget alert không tự động khóa chi tiêu.

## 23. Checklist CLI

- [ ] `gcloud --version` chạy được.
- [ ] `gcloud auth list` có đúng active account.
- [ ] `gcloud config get-value project` trả đúng Project ID.
- [ ] `gcloud projects describe` thành công.
- [ ] Billing được xác nhận bằng CLI hoặc Console.
- [ ] Đã chốt một region thống nhất.
- [ ] Đã chọn bucket name dự kiến.

## 24. Checklist repository

- [x] Có cloud YAML không chứa secret.
- [x] Có schema/model validation.
- [x] Có environment placeholder và missing-variable error.
- [x] Có naming/path validation.
- [x] Có structured JSON logging contract.
- [x] Có unit tests và CLI validator.
- [ ] Set đủ bốn environment variables thật.
- [ ] `validate_cloud_config.py` báo success.
- [ ] 4 tests pass.
- [ ] Ruff pass.

Chỉ chuyển sang `Dockerfile + .dockerignore` khi toàn bộ checklist trên hoàn thành.

## 25. Thông tin cần ghi lại, không chứa credential

Sau khi hoàn tất, ghi lại:

```text
Project name:
Project ID:
Billing linked: yes/no
Budget alert created: yes/no
Region:
Bucket name dự kiến:
Validator: success/fail
Tests:
Ruff:
```

Không ghi hoặc gửi:

```text
Payment/card information
Access token
Service-account private key
OAuth refresh token
Kaggle credential
```
